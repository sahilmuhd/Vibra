from django.db import transaction

from .models import HandRaise, RoomModerator, RoomParticipant, Seat


def user_in_room(room, user) -> bool:
    """Participants, the host and staff may read/act in a room."""
    if user.is_staff or room.host_id == user.id:
        return True
    return RoomParticipant.objects.filter(room=room, user=user).exists()


@transaction.atomic
def remove_user_from_room(room, user_id):
    """Frees any seat, withdraws a hand-raise and drops the participant row.
    Returns (freed_seat_positions, participant_was_removed). The caller
    broadcasts after the surrounding transaction commits."""
    freed = []
    for seat in Seat.objects.select_for_update().filter(room=room, user_id=user_id):
        seat.user = None
        seat.is_muted = True
        seat.muted_by_host = False
        seat.save(update_fields=["user", "is_muted", "muted_by_host"])
        freed.append(seat.position)
    HandRaise.objects.filter(room=room, user_id=user_id).delete()
    removed, _ = RoomParticipant.objects.filter(room=room, user_id=user_id).delete()
    return freed, bool(removed)


def is_host(room, user) -> bool:
    return user.is_staff or room.host_id == user.id


def is_moderator(room, user) -> bool:
    return RoomModerator.objects.filter(room=room, user=user).exists()


def can_moderate(room, user) -> bool:
    """Host, staff and appointed moderators may mute/lock/kick."""
    return is_host(room, user) or is_moderator(room, user)
