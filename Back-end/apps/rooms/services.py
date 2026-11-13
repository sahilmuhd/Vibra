from django.db import transaction

from apps.accounts.models import Block

from .models import HandRaise, RoomBan, RoomModerator, RoomMute, RoomParticipant, Seat

# Field values of an empty seat; every code path that frees a seat uses these.
VACANT_SEAT = {"user": None, "is_muted": True, "muted_by_host": False}


def setup_new_room(room, host):
    """Seats + host on seat 0 + host as first participant + tell followers."""
    from apps.notifications.services import notify_followers_live
    Seat.objects.bulk_create([Seat(room=room, position=i) for i in range(room.seat_count)])
    Seat.objects.filter(room=room, position=0).update(user=host, is_muted=False)
    RoomParticipant.objects.create(room=room, user=host)
    notify_followers_live(host, room)


@transaction.atomic
def create_live_room(host, *, name, category, description="", password=""):
    """Used by scheduled rooms ("Go live"); the REST create view shares setup_new_room()."""
    import uuid

    from django.contrib.auth.hashers import make_password
    from rest_framework.exceptions import PermissionDenied

    from apps.accounts.levels import is_admin
    from apps.accounts.profiles import ensure_profile

    from .models import Room
    ensure_profile(host)
    if Room.objects.filter(host=host, is_live=True).count() >= 3 and not is_admin(host):
        raise PermissionDenied("You can host at most 3 live rooms at a time.")
    room = Room.objects.create(
        name=name[:80], category=category, description=description[:200], host=host,
        voice_room_name=f"vibra-{uuid.uuid4().hex[:12]}",
        password=make_password(password) if password else "",
        seat_count=20 if is_admin(host) else 10,
    )
    setup_new_room(room, host)
    return room


def vacate(seat):
    """Free one (already locked) seat."""
    for field, value in VACANT_SEAT.items():
        setattr(seat, field, value)
    seat.save(update_fields=list(VACANT_SEAT))


def vacate_all(seats):
    """Free every seat in a queryset."""
    return seats.update(**VACANT_SEAT)


def parse_bool(value, default=True):
    """Lenient boolean from a JSON/form body ("false", 0, False -> False)."""
    if value is None:
        return default
    return value not in (False, "false", "False", 0, "0")


# --- roles -------------------------------------------------------------------

def is_host(room, user) -> bool:
    return user.is_staff or room.host_id == user.id


def is_moderator(room, user_id) -> bool:
    return RoomModerator.objects.filter(room=room, user_id=user_id).exists()


def can_moderate(room, user) -> bool:
    """Host, staff and appointed moderators may mute/lock/kick."""
    return is_host(room, user) or is_moderator(room, user.id)


def can_act_on(room, actor, target_user_id) -> bool:
    """Moderation targets: nobody may act on the host, and only the host may
    act on another moderator."""
    if target_user_id == room.host_id:
        return False
    return is_host(room, actor) or not is_moderator(room, target_user_id)


# --- membership ----------------------------------------------------------------

def is_banned(room, user_id) -> bool:
    return RoomBan.objects.filter(room=room, user_id=user_id).exists()


def shut_out(room, user_id) -> bool:
    """Kicked from this room, or blocked by its host."""
    return is_banned(room, user_id) or Block.objects.filter(
        blocker_id=room.host_id, blocked_id=user_id
    ).exists()


def user_in_room(room, user) -> bool:
    """Participants, the host and staff may read/act in a room."""
    if is_host(room, user):
        return True
    return RoomParticipant.objects.filter(room=room, user=user).exists()


def may_listen(room, user) -> bool:
    """Who may open the room's WebSocket."""
    if user.is_staff:
        return True
    return not shut_out(room, user.id) and user_in_room(room, user)


# --- host mute -----------------------------------------------------------------

def is_host_muted(room, user_id) -> bool:
    """A host/moderator mute sticks to the person for the room's lifetime, so
    changing seats or leaving and rejoining cannot undo it."""
    return RoomMute.objects.filter(room=room, user_id=user_id).exists()


def seat_user(seat, user_id, *, wants_mic):
    """Put `user_id` on a (locked) seat, honouring a standing host mute.
    Returns True when they may publish audio."""
    host_muted = is_host_muted(seat.room, user_id)
    seat.user_id = user_id
    seat.muted_by_host = host_muted
    seat.is_muted = host_muted or not wants_mic
    seat.save(update_fields=["user", "is_muted", "muted_by_host"])
    return not host_muted


@transaction.atomic
def remove_user_from_room(room, user_id):
    """Frees any seat, withdraws a hand-raise and drops the participant row.
    Returns (freed_seat_positions, participant_was_removed). The caller
    broadcasts after the surrounding transaction commits."""
    freed = []
    for seat in Seat.objects.select_for_update().filter(room=room, user_id=user_id):
        vacate(seat)
        freed.append(seat.position)
    HandRaise.objects.filter(room=room, user_id=user_id).delete()
    removed, _ = RoomParticipant.objects.filter(room=room, user_id=user_id).delete()
    return freed, bool(removed)
