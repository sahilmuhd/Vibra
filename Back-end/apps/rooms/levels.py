"""Room levels: a room grows with the coins gifted inside it.

Room level uses the same curve as user levels on (gift coins / 5), so
Lv5 needs 8 000 coins and Lv10 needs 40 500. Levels unlock mic seats:
10 seats to start, 15 at Lv5, 20 at Lv10. Rooms hosted by the main admin
get all 20 seats from the start.
"""
from django.db import transaction
from django.db.models import F, Sum

from apps.accounts.levels import is_admin, level_for, xp_for_level

XP_DIVISOR = 5
SEAT_TIERS = [(10, 20), (5, 15), (1, 10)]   # (min level, seats)
MAX_SEATS = 20


def room_level(gift_total):
    return level_for((gift_total or 0) // XP_DIVISOR)


def seats_for(level, admin_host=False):
    if admin_host:
        return MAX_SEATS
    return next(seats for need, seats in SEAT_TIERS if level >= need)


def level_info(gift_total):
    lvl = room_level(gift_total)
    nxt = xp_for_level(lvl + 1) * XP_DIVISOR
    next_unlock = next((need for need, _ in sorted(SEAT_TIERS) if need > lvl), None)
    return {
        "level": lvl, "coins": int(gift_total or 0),
        "next_level_at": nxt,
        "next_seat_unlock_level": next_unlock,
        "next_seat_unlock_at": xp_for_level(next_unlock) * XP_DIVISOR if next_unlock else None,
    }


def room_gift_total(room):
    from .models import GiftEvent
    return GiftEvent.objects.filter(room=room).aggregate(t=Sum(F("gift__cost") * F("combo")))["t"] or 0


def ensure_seats(room, gift_total=None):
    """Adds seat rows when the room's level (or an admin host) allows more.
    Returns the new seat count if seats were added, else None."""
    from .models import Room, Seat
    total = room_gift_total(room) if gift_total is None else gift_total
    target = seats_for(room_level(total), is_admin(room.host))
    with transaction.atomic():
        locked = Room.objects.select_for_update().get(pk=room.pk)
        if locked.seat_count >= target:
            return None
        Seat.objects.bulk_create([Seat(room=locked, position=i) for i in range(locked.seat_count, target)],
                                 ignore_conflicts=True)
        locked.seat_count = target
        locked.save(update_fields=["seat_count"])
    room.seat_count = target
    return target
