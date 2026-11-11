"""Server-side control of live LiveKit sessions.

A voice token is minted once, when a client joins, so its `can_publish` grant
goes stale the moment the user takes or loses a seat. These helpers push the
change to LiveKit so the permission follows the seat: a listener who takes a
seat can talk without reconnecting, and a speaker who is muted by the host,
kicked or evicted is cut off by the server rather than trusting the client.

Every call is best-effort. The database is the source of truth and is already
committed when these run, so a LiveKit outage is logged, never raised.
"""
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from livekit import api

logger = logging.getLogger(__name__)


def _http_url():
    return settings.LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")


def _enabled():
    return getattr(settings, "LIVEKIT_SYNC_ENABLED", False)


async def _call(fn):
    # livekit-api 0.7.x has no `async with` support, so close the session explicitly.
    lk = api.LiveKitAPI(_http_url(), settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    try:
        return await fn(lk)
    finally:
        await lk.aclose()


async def _update_permission(voice_room_name, user_id, can_publish):
    await _call(lambda lk: lk.room.update_participant(api.UpdateParticipantRequest(
        room=voice_room_name,
        identity=str(user_id),
        permission=api.ParticipantPermission(
            can_subscribe=True,
            can_publish=can_publish,
            can_publish_data=True,
        ),
    )))


async def _remove_participant(voice_room_name, user_id):
    await _call(lambda lk: lk.room.remove_participant(api.RoomParticipantIdentity(
        room=voice_room_name, identity=str(user_id),
    )))


async def _delete_room(voice_room_name):
    await _call(lambda lk: lk.room.delete_room(api.DeleteRoomRequest(room=voice_room_name)))


def _run(coro_fn, *args):
    if not _enabled():
        return
    try:
        async_to_sync(coro_fn)(*args)
    except api.TwirpError as exc:
        # "not_found": the user hasn't connected their voice yet (or already left).
        # Their next token is minted from the DB state, so nothing is lost.
        if getattr(exc, "code", None) == "not_found":
            logger.debug("LiveKit %s%r: %s", coro_fn.__name__, args, exc)
        else:
            logger.warning("LiveKit call %s%r failed: %s", coro_fn.__name__, args, exc)
    except Exception:  # noqa: BLE001 - LiveKit outage must not break the request
        logger.warning("LiveKit call %s%r failed", coro_fn.__name__, args, exc_info=True)


def set_can_publish(room, user_id, can_publish):
    """Allow or revoke publishing for one participant of a room's voice session."""
    _run(_update_permission, room.voice_room_name, user_id, can_publish)


def disconnect_user(room, user_id):
    """Kick one participant out of the room's voice session."""
    _run(_remove_participant, room.voice_room_name, user_id)


def close_room(room):
    """End the whole voice session (disconnects everyone)."""
    _run(_delete_room, room.voice_room_name)
