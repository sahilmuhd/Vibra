import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.serializers.json import DjangoJSONEncoder

logger = logging.getLogger(__name__)


def broadcast_to_room(room_id: int, event_type: str, payload: dict) -> None:
    """Send an event to every client connected to a room's WebSocket group.
    Called from regular DRF views (seat changes, messages, gifts) so the
    REST API stays the single source of truth and Channels is purely fan-out.

    event_type uses dot notation (e.g. "seat.update") which Channels maps to
    the `seat_update` handler method on RoomConsumer.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return  # Channels not configured (e.g. running plain manage.py test)

    # Round-trip through JSON so datetimes/Decimals from serializers become
    # plain strings before hitting the channel layer's own pickling.
    safe_payload = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))

    # The DB change is already committed when this runs. If Redis is down,
    # fan-out is lost but the request must not 500 (clients re-sync on reconnect).
    try:
        async_to_sync(channel_layer.group_send)(
            f"room_{room_id}",
            {"type": event_type.replace(".", "_"), "payload": safe_payload},
        )
    except Exception:  # noqa: BLE001
        logger.exception("broadcast_to_room failed (room=%s, event=%s)", room_id, event_type)
