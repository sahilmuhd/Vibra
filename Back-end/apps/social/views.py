from datetime import timedelta

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.profiles import ensure_profile
from apps.accounts.serializers import PublicUserSerializer
from apps.rooms.models import Room, RoomParticipant
from apps.rooms.realtime import broadcast_to_user

from . import services
from .models import (
    Bond, BondRequest, Family, FamilyMember, FamilyMessage, ProfileVisit, RoomReminder, ScheduledRoom,
)

User = get_user_model()


def family_card(f, me_family_id=None):
    return {
        "id": f.id, "name": f.name, "tag": f.tag, "emblem": f.emblem, "description": f.description,
        "members": getattr(f, "member_count", None) if getattr(f, "member_count", None) is not None else f.members.count(),
        "max_members": Family.MAX_MEMBERS, "score": getattr(f, "score", 0) or 0,
        "is_mine": me_family_id == f.id,
    }


def my_family_id(user):
    m = FamilyMember.objects.filter(user=user).only("family_id").first()
    return m.family_id if m else None


# ------------------------------------------------------------------ families
class FamilyListView(APIView):
    """GET ?q= : families by weekly score. POST: create {name, tag, emblem, description}."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Family.objects.all()
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(tag__iexact=q)
        qs = services.family_scores(qs, timezone.now() - timedelta(days=7)).order_by("-score", "-member_count", "id")[:50]
        mine = my_family_id(request.user)
        return Response({"my_family_id": mine, "families": [family_card(f, mine) for f in qs]})

    def post(self, request):
        d = request.data
        f = services.create_family(request.user, name=d.get("name"), tag=d.get("tag"),
                                   emblem=d.get("emblem"), description=d.get("description"))
        return Response(family_card(f, f.id), status=status.HTTP_201_CREATED)


class FamilyDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, family_id):
        week = timezone.now() - timedelta(days=7)
        f = get_object_or_404(services.family_scores(Family.objects.all(), week), id=family_id)
        rank = services.family_scores(Family.objects.all(), week).filter(score__gt=f.score).count() + 1 if f.score else None
        members = FamilyMember.objects.filter(family=f).select_related("user__profile")
        me = next((m for m in members if m.user_id == request.user.id), None)
        member_ids = [m.user_id for m in members]
        live = (Room.objects.filter(is_live=True, host_id__in=member_ids).select_related("host__profile")
                .order_by("-created_at")[:10])
        order = {FamilyMember.ROLE_OWNER: 0, FamilyMember.ROLE_ELDER: 1, FamilyMember.ROLE_MEMBER: 2}
        return Response({
            **family_card(f, my_family_id(request.user)),
            "rank": rank,
            "my_role": me.role if me else None,
            "members_list": [{"user": PublicUserSerializer(m.user).data, "role": m.role, "joined_at": m.joined_at}
                             for m in sorted(members, key=lambda m: (order[m.role], m.joined_at))],
            "live_rooms": [{"id": r.id, "name": r.name, "host": PublicUserSerializer(r.host).data} for r in live],
        })

    def patch(self, request, family_id):
        f = get_object_or_404(Family, id=family_id)
        if f.owner_id != request.user.id:
            raise PermissionDenied("Only the owner can edit the family.")
        if "description" in request.data:
            f.description = str(request.data.get("description") or "").strip()[:200]
        if request.data.get("emblem") in Family.EMBLEMS:
            f.emblem = request.data["emblem"]
        f.save(update_fields=["description", "emblem"])
        return Response(family_card(f, f.id))


class FamilyActionView(APIView):
    """POST join | leave | kick {user_id} | role {user_id, role}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, family_id, action):
        f = get_object_or_404(Family, id=family_id)
        if action == "join":
            services.join_family(request.user, f)
        elif action == "leave":
            m = services.member_of(f, request.user)
            if m is None:
                raise ValidationError("You are not in this family.")
            services.leave_family(request.user)
        elif action == "kick":
            services.kick_member(request.user, f, _int(request.data.get("user_id")))
        elif action == "role":
            services.set_role(request.user, f, _int(request.data.get("user_id")), request.data.get("role"))
        else:
            return Response({"detail": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True})


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValidationError("A valid user_id is required.")


class FamilyChatView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "chat"

    def _family(self, request, family_id):
        f = get_object_or_404(Family, id=family_id)
        if services.member_of(f, request.user) is None:
            raise PermissionDenied("Only members can read the family chat.")
        return f

    def get(self, request, family_id):
        f = self._family(request, family_id)
        rows = list(FamilyMessage.objects.filter(family=f).select_related("user__profile").order_by("-id")[:60])[::-1]
        return Response([_fmsg(m) for m in rows])

    def post(self, request, family_id):
        f = self._family(request, family_id)
        text = " ".join(str(request.data.get("text") or "").split())[:300]
        if not text:
            raise ValidationError({"text": "Message cannot be empty."})
        m = FamilyMessage.objects.create(family=f, user=request.user, text=text)
        data = _fmsg(m)
        for uid in FamilyMember.objects.filter(family=f).values_list("user_id", flat=True):
            broadcast_to_user(uid, "family.message", {"family_id": f.id, "message": data})
        return Response(data, status=status.HTTP_201_CREATED)


def _fmsg(m):
    return {"id": m.id, "text": m.text, "created_at": m.created_at,
            "user": PublicUserSerializer(m.user).data if m.user and hasattr(m.user, "profile") else None}


# ------------------------------------------------------------------ bonds
class BondsView(APIView):
    """GET: my bonds + pending requests. POST {user_id, kind}: send a request (pays up front)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        me = request.user
        reqs = BondRequest.objects.filter(status=BondRequest.PENDING).select_related("from_user__profile", "to_user__profile")
        return Response({
            "bonds": [_bond(b, other) for b, other in services.bonds_of(me.id)],
            "incoming": [_req(r, r.from_user) for r in reqs.filter(to_user=me)],
            "outgoing": [_req(r, r.to_user) for r in reqs.filter(from_user=me)],
            "costs": Bond.COST, "max_bff": Bond.MAX_BFF,
        })

    def post(self, request):
        target = get_object_or_404(User, id=_int(request.data.get("user_id")))
        req = services.request_bond(request.user, target, request.data.get("kind"))
        from apps.wallet.services import get_balance
        return Response({"id": req.id, "balance": get_balance(request.user)}, status=status.HTTP_201_CREATED)


class BondRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, req_id, action):
        req = services.answer_bond(request.user, req_id, action)
        return Response({"status": req.status})


class BreakBondView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        services.break_bond(request.user, user_id)
        return Response({"ok": True})


class UserBondsView(APIView):
    """Public: someone's CP and best friends, for their profile page."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        get_object_or_404(User, id=user_id)
        me = request.user.id
        pending = BondRequest.objects.filter(status=BondRequest.PENDING, from_user_id__in=[me, user_id],
                                             to_user_id__in=[me, user_id]).exclude(from_user_id=user_id, to_user_id=user_id).first()
        bond = services.bond_between(me, user_id) if me != user_id else None
        return Response({
            "bonds": [_bond(b, other) for b, other in services.bonds_of(user_id)],
            "with_me": bond.kind if bond else None,
            "pending_with_me": ({"id": pending.id, "kind": pending.kind, "from_me": pending.from_user_id == me}
                                if pending and me != user_id else None),
            "costs": Bond.COST,
        })


def _bond(b, other):
    return {"kind": b.kind, "since": b.created_at, "user": PublicUserSerializer(other).data}


def _req(r, other):
    return {"id": r.id, "kind": r.kind, "cost": r.cost, "created_at": r.created_at, "user": PublicUserSerializer(other).data}


# ------------------------------------------------------------------ visitors & friends live
class VisitorsView(APIView):
    """GET: who viewed my profile (newest first) + how many are new. POST: mark all seen."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rows = ProfileVisit.objects.filter(viewed=request.user).select_related("viewer__profile").order_by("-last_at")[:50]
        seen = ensure_profile(request.user).visitors_seen_at
        return Response({
            "new": services.new_visitor_count(request.user),
            "visitors": [{"user": PublicUserSerializer(v.viewer).data, "count": v.count, "last_at": v.last_at,
                          "is_new": not seen or v.last_at > seen} for v in rows if hasattr(v.viewer, "profile")],
        })

    def post(self, request):
        p = ensure_profile(request.user)
        p.visitors_seen_at = timezone.now()
        p.save(update_fields=["visitors_seen_at"])
        return Response({"new": 0})


class FriendsLiveView(APIView):
    """People I follow who are in a live room right now."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        following = request.user.following_set.values("following_id")
        rows = (RoomParticipant.objects.filter(user_id__in=following, room__is_live=True)
                .select_related("user__profile", "room").order_by("-joined_at")[:30])
        seen, out = set(), []
        for p in rows:
            if p.user_id in seen or not hasattr(p.user, "profile"):
                continue
            seen.add(p.user_id)
            out.append({"user": PublicUserSerializer(p.user).data, "room": {"id": p.room_id, "name": p.room.name}})
        return Response(out)


# ------------------------------------------------------------------ voice clips
class VoiceUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "upload"

    def post(self, request):
        clip = services.save_voice(request.user, request.FILES.get("audio"), request.data.get("seconds"))
        return Response(services.voice_payload(clip, request), status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ scheduled rooms
def _sched(s, me, reminded_ids):
    return {
        "id": s.id, "title": s.title, "description": s.description, "category": s.category,
        "starts_at": s.starts_at, "host": PublicUserSerializer(s.host).data,
        "reminders": getattr(s, "reminder_count", 0), "reminded": s.id in reminded_ids,
        "is_mine": s.host_id == me.id,
    }


class ScheduledListView(APIView):
    """GET ?scope=all|following|mine — upcoming rooms. POST {title, description, category, starts_at}."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        scope = request.query_params.get("scope", "all")
        qs = services.upcoming().select_related("host__profile").annotate(reminder_count=Count("reminders"))
        if scope == "following":
            qs = qs.filter(host__follower_set__follower=request.user)
        elif scope == "mine":
            qs = qs.filter(host=request.user)
        rows = list(qs.order_by("starts_at")[:30])
        reminded = set(RoomReminder.objects.filter(user=request.user, scheduled__in=rows).values_list("scheduled_id", flat=True))
        return Response([_sched(s, request.user, reminded) for s in rows])

    def post(self, request):
        d = request.data
        starts = parse_datetime(str(d.get("starts_at") or ""))
        if starts is not None and timezone.is_naive(starts):
            starts = timezone.make_aware(starts)
        s = services.schedule_room(request.user, title=d.get("title"), description=d.get("description"),
                                   category=str(d.get("category") or "talk").lower(), starts_at=starts)
        return Response(_sched(s, request.user, set()), status=status.HTTP_201_CREATED)


class ScheduledActionView(APIView):
    """POST remind (toggle) | cancel (host) | start (host: go live now)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, sched_id, action):
        s = get_object_or_404(ScheduledRoom, id=sched_id)
        if action == "remind":
            if s.host_id == request.user.id:
                raise ValidationError("It's your own room.")
            r, created = RoomReminder.objects.get_or_create(user=request.user, scheduled=s)
            if not created:
                r.delete()
            return Response({"reminded": created, "reminders": s.reminders.count()})
        if s.host_id != request.user.id:
            raise PermissionDenied("Only the host can do that.")
        if s.cancelled or s.room_id:
            raise ValidationError("This scheduled room is closed.")
        if action == "cancel":
            s.cancelled = True
            s.save(update_fields=["cancelled"])
            return Response({"cancelled": True})
        if action == "start":
            if s.starts_at - timezone.now() > timedelta(minutes=15):
                raise ValidationError("You can go live from 15 minutes before the start time.")
            from apps.notifications.services import notify
            from apps.rooms.services import create_live_room
            room = create_live_room(request.user, name=s.title, category=s.category, description=s.description)
            s.room = room
            s.save(update_fields=["room"])
            name = ensure_profile(request.user).username
            for r in s.reminders.select_related("user"):
                notify(r.user, request.user, "live", f"🔴 {name} is live: {s.title}", room=room)
            return Response({"room_id": room.id}, status=status.HTTP_201_CREATED)
        return Response({"detail": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
