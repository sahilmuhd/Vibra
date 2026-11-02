from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.rooms.models import HandRaise, Room, RoomParticipant, Seat
from apps.rooms.realtime import broadcast_to_room
from apps.rooms.services import remove_user_from_room


class Command(BaseCommand):
    help = (
        "Remove participants whose WebSocket heartbeat stopped and end live rooms "
        "that have nobody left. Run every minute or two from a cron job."
    )

    def add_arguments(self, parser):
        parser.add_argument("--participant-minutes", type=int, default=3)
        parser.add_argument("--empty-room-minutes", type=int, default=5)

    def handle(self, *args, **opts):
        now = timezone.now()
        stale = RoomParticipant.objects.filter(
            last_seen__lt=now - timedelta(minutes=opts["participant_minutes"]),
            room__is_live=True,
        ).select_related("room")
        dropped = 0
        for participant in list(stale):
            freed, removed = remove_user_from_room(participant.room, participant.user_id)
            for position in freed:
                broadcast_to_room(participant.room_id, "seat.update", {"position": position, "action": "left"})
            if removed:
                dropped += 1
                broadcast_to_room(participant.room_id, "presence.update", {
                    "user_id": participant.user_id,
                    "action": "left",
                    "online_count": RoomParticipant.objects.filter(room=participant.room).count(),
                })

        ended = 0
        empty = Room.objects.filter(
            is_live=True,
            created_at__lt=now - timedelta(minutes=opts["empty_room_minutes"]),
        ).exclude(participants__isnull=False)
        for room in list(empty):
            with transaction.atomic():
                room.is_live = False
                room.save(update_fields=["is_live"])
                Seat.objects.filter(room=room).update(user=None, is_muted=True, muted_by_host=False)
                HandRaise.objects.filter(room=room).delete()
            broadcast_to_room(room.id, "room.ended", {"room_id": room.id})
            ended += 1

        self.stdout.write(f"dropped {dropped} stale participants, ended {ended} empty rooms")
