import asyncio
import time

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from .models import Room, RoomParticipant
from .services import may_listen

HEARTBEAT_SECONDS = 60
MIN_TICK_INTERVAL = 0.1       # speaking_tick: at most ~10/s per connection
MIN_REACTION_INTERVAL = 0.5   # reaction: at most 2/s per connection


class RoomConsumer(AsyncJsonWebsocketConsumer):
    """
    Client connects to: wss://<host>/ws/rooms/<room_id>/?token=<jwt>
    This consumer does NOT accept client-sent state changes directly — all
    mutations (take seat, send message, send gift) go through the normal
    DRF endpoints, which then call broadcast_to_room(). This consumer is
    fan-out only. Keeping "write" on HTTP and "fan-out" on WS means you get
    normal DRF validation/permissions for every mutation instead of
    duplicating that logic in the socket layer.

    Only users who are in the room (participants, the host, staff) may
    listen. Join/leave presence is announced by the REST endpoints; while a
    socket is open it refreshes the participant's `last_seen` so the
    `cleanup_stale_rooms` command can drop users whose client vanished.
    """

    async def connect(self):
        self._joined_group = False
        self._heartbeat_task = None
        self._last_tick = 0.0
        self._last_reaction = 0.0
        self.user = self.scope.get("user")
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"room_{self.room_id}"

        if self.user is None or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        if not await self.room_is_live(self.room_id):
            await self.close(code=4004)
            return

        if not await self.may_listen(self.room_id, self.user):
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self._joined_group = True
        await self.accept()
        await self.touch()
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat())

    async def disconnect(self, close_code):
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        if self._joined_group:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self.touch()

    async def receive_json(self, content, **kwargs):
        # Only lightweight, non-authoritative signals go over the socket
        # directly — e.g. "I am currently speaking" volume ticks for the
        # mic-pulse animation. Anything that changes stored state (messages,
        # seats, gifts) must go through the REST endpoints instead.
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        now = time.monotonic()
        if kind == "speaking_tick":
            if now - self._last_tick < MIN_TICK_INTERVAL:
                return
            self._last_tick = now
            try:
                level = max(0.0, min(1.0, float(content.get("level", 0))))
            except (TypeError, ValueError):
                return
            if level != level:  # NaN
                return
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "speaking_tick",
                    "payload": {"user_id": self.user.id, "level": level},
                },
            )
        elif kind == "reaction":
            if now - self._last_reaction < MIN_REACTION_INTERVAL:
                return
            self._last_reaction = now
            emoji = str(content.get("emoji", "❤️"))[:4]
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "reaction_event",
                    "payload": {"user_id": self.user.id, "emoji": emoji},
                },
            )
        elif kind == "ping":
            await self.touch()

    # --- Group event handlers: method name = event "type" with dots -> underscores ---

    async def reaction_event(self, event):
        await self.send_json({"event": "reaction", **event["payload"]})

    async def seat_update(self, event):
        await self.send_json({"event": "seat_update", **event["payload"]})

    async def seat_mute(self, event):
        await self.send_json({"event": "seat_mute", **event["payload"]})

    async def hand_raised(self, event):
        await self.send_json({"event": "hand_raised", **event["payload"]})

    async def hand_lowered(self, event):
        await self.send_json({"event": "hand_lowered", **event["payload"]})

    async def room_ended(self, event):
        await self.send_json({"event": "room_ended", **event["payload"]})
        await self.close(code=4004)

    async def seat_lock(self, event):
        await self.send_json({"event": "seat_lock", **event["payload"]})

    async def participant_kicked(self, event):
        await self.send_json({"event": "participant_kicked", **event["payload"]})
        if event["payload"].get("user_id") == self.user.id:
            await self.close(code=4003)

    async def moderators_update(self, event):
        await self.send_json({"event": "moderators_update", **event["payload"]})

    async def message_new(self, event):
        await self.send_json({"event": "message_new", **event["payload"]})

    async def gift_sent(self, event):
        await self.send_json({"event": "gift_sent", **event["payload"]})

    async def presence_update(self, event):
        await self.send_json({"event": "presence_update", **event["payload"]})

    async def speaking_tick(self, event):
        await self.send_json({"event": "speaking_tick", **event["payload"]})

    @staticmethod
    async def room_is_live(room_id):
        return await sync_to_async(Room.objects.filter(id=room_id, is_live=True).exists)()

    @staticmethod
    async def may_listen(room_id, user):
        def check():
            room = Room.objects.filter(id=room_id).first()
            return room is not None and may_listen(room, user)
        return await sync_to_async(check)()

    async def touch(self):
        await sync_to_async(
            RoomParticipant.objects.filter(room_id=self.room_id, user=self.user).update
        )(last_seen=timezone.now())


class UserConsumer(AsyncJsonWebsocketConsumer):
    """Personal channel: wss://<host>/ws/me/?token=<jwt>
    Receive-only fan-out of events addressed to one user (new DMs,
    notifications). Clients never send anything meaningful on it."""

    async def connect(self):
        self.group_name = None
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.channel_layer.group_add("everyone", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self.channel_layer.group_discard("everyone", self.channel_name)

    async def receive_json(self, content, **kwargs):
        return  # nothing to accept from clients

    async def gift_global(self, event):
        await self.send_json({"event": "gift_global", **event["payload"]})

    async def dm_new(self, event):
        await self.send_json({"event": "dm_new", **event["payload"]})

    async def notification_new(self, event):
        await self.send_json({"event": "notification_new", **event["payload"]})
