import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.levels import is_admin
from apps.accounts.profiles import ensure_profile
from apps.notifications.services import notify
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .models import Bond, BondRequest, Family, FamilyMember, ProfileVisit, ScheduledRoom, VoiceClip

TAG_RE = re.compile(r"^[A-Z0-9]{2,6}$")
PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}


def lock_user(user):
    get_user_model().objects.select_for_update().get(pk=user.pk)


def charge(user, amount, label, type_=Transaction.TYPE_SHOP):
    """Debit coins (the admin pays nothing for perks). Caller holds the user lock."""
    if amount <= 0 or is_admin(user):
        return 0
    if get_balance(user) < amount:
        raise ValidationError("Not enough coins.")
    Transaction.objects.create(user=user, type=type_, amount=-amount, label=label)
    return amount


# ------------------------------------------------------------------ families
def _sync_profile_family(user_id, family):
    from apps.accounts.models import Profile
    Profile.objects.filter(user_id=user_id).update(
        family_id=family.id if family else None, family_tag=family.tag if family else "")


def family_scores(qs, since):
    """Annotate families with the coins their members gifted since `since`."""
    from apps.rooms.models import GiftEvent
    sub = (GiftEvent.objects.filter(created_at__gte=since, sender__family_membership__family=OuterRef("pk"))
           .values("sender__family_membership__family")
           .annotate(t=Sum(F("gift__cost") * F("combo"))).values("t")[:1])
    return qs.annotate(score=Coalesce(Subquery(sub, output_field=IntegerField()), 0),
                       member_count=Count("members", distinct=True))


@transaction.atomic
def create_family(user, *, name, tag, emblem, description=""):
    name = " ".join(str(name or "").split())
    tag = str(tag or "").strip().upper()
    if not 3 <= len(name) <= 40:
        raise ValidationError({"name": "Family name must be 3-40 characters."})
    if not TAG_RE.match(tag):
        raise ValidationError({"tag": "Tag must be 2-6 letters or numbers."})
    if emblem not in Family.EMBLEMS:
        emblem = "crown"
    if FamilyMember.objects.filter(user=user).exists():
        raise ValidationError("Leave your current family first.")
    if Family.objects.filter(name__iexact=name).exists():
        raise ValidationError({"name": "That family name is taken."})
    family = Family.objects.create(name=name, tag=tag, emblem=emblem,
                                   description=str(description or "").strip()[:200], owner=user)
    FamilyMember.objects.create(family=family, user=user, role=FamilyMember.ROLE_OWNER)
    _sync_profile_family(user.id, family)
    return family


@transaction.atomic
def join_family(user, family):
    if FamilyMember.objects.filter(user=user).exists():
        raise ValidationError("You are already in a family.")
    Family.objects.select_for_update().get(pk=family.pk)
    if family.members.count() >= Family.MAX_MEMBERS:
        raise ValidationError("This family is full.")
    FamilyMember.objects.create(family=family, user=user)
    _sync_profile_family(user.id, family)
    notify(family.owner, user, "family", f"{ensure_profile(user).username} joined {family.name}")


@transaction.atomic
def leave_family(user):
    m = FamilyMember.objects.select_related("family").filter(user=user).first()
    if m is None:
        raise ValidationError("You are not in a family.")
    family = m.family
    m.delete()
    _sync_profile_family(user.id, None)
    if m.role == FamilyMember.ROLE_OWNER:
        heir = (family.members.filter(role=FamilyMember.ROLE_ELDER).first() or family.members.first())
        if heir is None:
            family.delete()
            return None
        heir.role = FamilyMember.ROLE_OWNER
        heir.save(update_fields=["role"])
        family.owner_id = heir.user_id
        family.save(update_fields=["owner"])
    return family


def member_of(family, user):
    return FamilyMember.objects.filter(family=family, user=user).first()


@transaction.atomic
def kick_member(actor, family, target_id):
    me = member_of(family, actor)
    target = FamilyMember.objects.filter(family=family, user_id=target_id).first()
    if me is None or me.role == FamilyMember.ROLE_MEMBER or target is None or target.user_id == actor.id:
        raise PermissionDenied("You can't remove this member.")
    if target.role == FamilyMember.ROLE_OWNER or (me.role == FamilyMember.ROLE_ELDER and target.role != FamilyMember.ROLE_MEMBER):
        raise PermissionDenied("Elders can only remove members.")
    target.delete()
    _sync_profile_family(target_id, None)


def set_role(actor, family, target_id, role):
    if family.owner_id != actor.id:
        raise PermissionDenied("Only the owner can change roles.")
    if role not in (FamilyMember.ROLE_ELDER, FamilyMember.ROLE_MEMBER):
        raise ValidationError("Role must be elder or member.")
    updated = FamilyMember.objects.filter(family=family, user_id=target_id).exclude(role=FamilyMember.ROLE_OWNER).update(role=role)
    if not updated:
        raise ValidationError("That person is not a member.")


# ------------------------------------------------------------------ bonds (CP / best friend)
def ordered(a_id, b_id):
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def bond_between(a_id, b_id):
    a, b = ordered(a_id, b_id)
    return Bond.objects.filter(user_a_id=a, user_b_id=b).first()


def count_bonds(user_id, kind):
    return Bond.objects.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id), kind=kind).count()


def check_room_for_bond(user_id, kind, who="You"):
    if kind == Bond.KIND_CP and count_bonds(user_id, kind):
        raise ValidationError(f"{who} already {'have' if who == 'You' else 'has'} a CP.")
    if kind == Bond.KIND_BFF and count_bonds(user_id, kind) >= Bond.MAX_BFF:
        raise ValidationError(f"{who} already {'have' if who == 'You' else 'has'} {Bond.MAX_BFF} best friends.")


@transaction.atomic
def request_bond(user, target, kind):
    if kind not in dict(Bond.KINDS):
        raise ValidationError("Choose cp or bff.")
    if target.id == user.id:
        raise ValidationError("You can't bond with yourself.")
    from apps.accounts.models import Block
    if Block.between(user.id, target.id):
        raise PermissionDenied("You can't send this request.")
    if bond_between(user.id, target.id):
        raise ValidationError("You are already bonded.")
    if BondRequest.objects.filter(Q(from_user=user, to_user=target) | Q(from_user=target, to_user=user),
                                  status=BondRequest.PENDING).exists():
        raise ValidationError("There is already a pending request between you.")
    check_room_for_bond(user.id, kind)
    check_room_for_bond(target.id, kind, who="They")
    lock_user(user)
    cost = charge(user, Bond.COST[kind], "CP ring" if kind == Bond.KIND_CP else "Best-friend bracelet")
    req = BondRequest.objects.create(from_user=user, to_user=target, kind=kind, cost=cost)
    name = ensure_profile(user).username
    notify(target, user, "bond", f"💍 {name} wants to be your CP" if kind == Bond.KIND_CP
           else f"🤝 {name} wants to be your best friend")
    return req


def _refund(req, why):
    if req.cost:
        Transaction.objects.create(user=req.from_user, type=Transaction.TYPE_BONUS, amount=req.cost,
                                   label=f"Refund: bond request {why}")


@transaction.atomic
def answer_bond(user, req_id, action):
    req = BondRequest.objects.select_for_update().filter(id=req_id, status=BondRequest.PENDING).first()
    if req is None:
        raise ValidationError("This request is no longer open.")
    if action == "cancel":
        if req.from_user_id != user.id:
            raise PermissionDenied("Not your request.")
        req.status = BondRequest.CANCELLED
        _refund(req, "cancelled")
    elif action in ("accept", "decline"):
        if req.to_user_id != user.id:
            raise PermissionDenied("Not your request.")
        if action == "decline":
            req.status = BondRequest.DECLINED
            _refund(req, "declined")
        else:
            check_room_for_bond(user.id, req.kind)
            check_room_for_bond(req.from_user_id, req.kind, who="They")
            if bond_between(user.id, req.from_user_id):
                raise ValidationError("You are already bonded.")
            a, b = ordered(user.id, req.from_user_id)
            Bond.objects.create(user_a_id=a, user_b_id=b, kind=req.kind)
            req.status = BondRequest.ACCEPTED
            if req.kind == Bond.KIND_CP:
                _sync_cp(user, req.from_user)
            name = ensure_profile(user).username
            notify(req.from_user, user, "bond", f"💞 {name} is now your CP!" if req.kind == Bond.KIND_CP
                   else f"🤝 {name} is now your best friend!")
    else:
        raise ValidationError("Unknown action.")
    req.save(update_fields=["status"])
    return req


def _sync_cp(u1, u2):
    from apps.accounts.models import Profile
    p1, p2 = ensure_profile(u1), ensure_profile(u2)
    Profile.objects.filter(pk=p1.pk).update(cp_partner=u2, cp_name=p2.username)
    Profile.objects.filter(pk=p2.pk).update(cp_partner=u1, cp_name=p1.username)


@transaction.atomic
def break_bond(user, other_id):
    bond = bond_between(user.id, other_id)
    if bond is None:
        raise ValidationError("You are not bonded.")
    if bond.kind == Bond.KIND_CP:
        from apps.accounts.models import Profile
        Profile.objects.filter(user_id__in=[user.id, other_id]).update(cp_partner=None, cp_name="")
    bond.delete()


def bonds_of(user_id):
    rows = (Bond.objects.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id))
            .select_related("user_a__profile", "user_b__profile").order_by("kind", "created_at"))
    return [(b, b.other(user_id)) for b in rows]


# ------------------------------------------------------------------ visitors
def record_visit(viewer, viewed_user_id):
    if viewer.id == viewed_user_id:
        return
    now = timezone.now()
    updated = ProfileVisit.objects.filter(viewer=viewer, viewed_id=viewed_user_id).update(
        count=F("count") + 1, last_at=now)
    if not updated:
        ProfileVisit.objects.get_or_create(viewer=viewer, viewed_id=viewed_user_id, defaults={"last_at": now})


def new_visitor_count(user):
    seen = ensure_profile(user).visitors_seen_at
    qs = ProfileVisit.objects.filter(viewed=user)
    return qs.filter(last_at__gt=seen).count() if seen else qs.count()


# ------------------------------------------------------------------ voice clips
MAGIC = [
    (b"\x1aE\xdf\xa3", "webm"), (b"OggS", "ogg"), (b"ID3", "mp3"), (b"\xff\xfb", "mp3"), (b"\xff\xf3", "mp3"),
    (b"RIFF", "wav"),
]


def sniff_audio(head):
    for sig, ext in MAGIC:
        if head.startswith(sig):
            return ext
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


def save_voice(user, upload, seconds):
    if upload is None:
        raise ValidationError({"audio": "Record something first."})
    if upload.size > VoiceClip.MAX_BYTES:
        raise ValidationError({"audio": "Voice messages can be up to 60 seconds."})
    head = upload.read(16)
    ext = sniff_audio(head)
    if ext is None:
        raise ValidationError({"audio": "That doesn't look like a voice recording."})
    try:
        seconds = max(1, min(VoiceClip.MAX_SECONDS, int(round(float(seconds)))))
    except (TypeError, ValueError):
        seconds = 1
    folder = settings.MEDIA_ROOT / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{user.id}-{secrets.token_hex(10)}.{ext}"
    upload.seek(0)
    with open(folder / name, "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    return VoiceClip.objects.create(owner=user, file=name, seconds=seconds)


def claim_voice(user, voice_id):
    """A clip the caller uploaded, not yet used — or a validation error."""
    if voice_id in (None, ""):
        return None
    try:
        clip = VoiceClip.objects.get(id=int(voice_id), owner=user)
    except (VoiceClip.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"voice_id": "Voice message not found."})
    return clip


def voice_payload(clip, request=None):
    if clip is None:
        return None
    url = clip.url_path
    if request is not None:
        url = request.build_absolute_uri(url)
    return {"id": clip.id, "url": url, "seconds": clip.seconds}


# ------------------------------------------------------------------ scheduled rooms
MAX_UPCOMING_PER_HOST = 5


def upcoming(qs=None):
    qs = qs if qs is not None else ScheduledRoom.objects.all()
    return qs.filter(cancelled=False, room__isnull=True, starts_at__gt=timezone.now() - timedelta(hours=2))


def schedule_room(user, *, title, description, category, starts_at):
    from apps.rooms.models import Room
    title = " ".join(str(title or "").split())
    if not 2 <= len(title) <= 80:
        raise ValidationError({"title": "Title must be 2-80 characters."})
    if category not in dict(Room.CATEGORY_CHOICES):
        raise ValidationError({"category": "Choose a category."})
    now = timezone.now()
    if starts_at is None or starts_at < now + timedelta(minutes=5) or starts_at > now + timedelta(days=30):
        raise ValidationError({"starts_at": "Pick a time between 5 minutes and 30 days from now."})
    if upcoming(ScheduledRoom.objects.filter(host=user)).count() >= MAX_UPCOMING_PER_HOST:
        raise ValidationError(f"You can have at most {MAX_UPCOMING_PER_HOST} upcoming rooms.")
    return ScheduledRoom.objects.create(host=user, title=title, description=str(description or "").strip()[:200],
                                        category=category, starts_at=starts_at)


def send_due_reminders(now=None):
    """Called by the cleanup timer: 'starting soon' to everyone who tapped Remind me."""
    from apps.rooms.realtime import broadcast_to_user
    now = now or timezone.now()
    due = upcoming(ScheduledRoom.objects.filter(reminded_at__isnull=True, starts_at__lte=now + timedelta(minutes=5)))
    sent = 0
    for s in due.select_related("host__profile"):
        name = ensure_profile(s.host).username
        for r in s.reminders.select_related("user"):
            notify(r.user, s.host, "scheduled", f"⏰ {name}'s room “{s.title}” is starting soon")
            sent += 1
        notify(s.host, None, "scheduled", f"⏰ Your room “{s.title}” starts soon — tap Go live")
        broadcast_to_user(s.host_id, "scheduled.due", {"id": s.id})
        s.reminded_at = now
        s.save(update_fields=["reminded_at"])
    return sent
