import json

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Room


class RoomConsumer(AsyncJsonWebsocketConsumer):
    """
    Client connects to: wss://<host>/ws/rooms/<room_id>/?token=<jwt>
    This consumer does NOT accept client-sent state changes directly — all
    mutations (take seat, send message, send gift) go through the normal
    DRF endpoints, which then call broadcast_to_room(). This consumer is
    fan-out only. Keeping "write" on HTTP and "fan-out" on WS means you get
    normal DRF validation/permissions for every mutation instead of
    duplicating that logic in the socket layer.
    """

    async def connect(self):
        self._announced = False  # only announce "left" for connections that announced "joined"
        self.user = self.scope.get("user")
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"room_{self.room_id}"

        if self.user is None or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        room_exists = await self.room_exists(self.room_id)
        if not room_exists:
            await self.close(code=4004)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        self._announced = True
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "presence_update", "payload": {"user_id": self.user.id, "action": "joined"}},
        )

    async def disconnect(self, close_code):
        # Previously this ran for rejected connections too, letting an
        # unauthenticated socket broadcast {"user_id": null, "action": "left"}
        # into any room's group.
        if getattr(self, "_announced", False):
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "presence_update", "payload": {"user_id": self.user.id, "action": "left"}},
            )
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Only lightweight, non-authoritative signals go over the socket
        # directly — e.g. "I am currently speaking" volume ticks for the
        # mic-pulse animation. Anything that changes stored state (messages,
        # seats, gifts) must go through the REST endpoints instead.
        if not isinstance(content, dict):
            return
        if content.get("type") == "speaking_tick":
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "speaking_tick",
                    "payload": {"user_id": self.user.id, "level": content.get("level", 0)},
                },
            )

    # --- Group event handlers: method name = event "type" with dots -> underscores ---

    async def seat_update(self, event):
        await self.send_json({"event": "seat_update", **event["payload"]})

    async def seat_mute(self, event):
        await self.send_json({"event": "seat_mute", **event["payload"]})

    async def hand_raised(self, event):
        await self.send_json({"event": "hand_raised", **event["payload"]})

    async def message_new(self, event):
        await self.send_json({"event": "message_new", **event["payload"]})

    async def gift_sent(self, event):
        await self.send_json({"event": "gift_sent", **event})

    async def presence_update(self, event):
        await self.send_json({"event": "presence_update", **event["payload"]})

    async def speaking_tick(self, event):
        await self.send_json({"event": "speaking_tick", **event["payload"]})

    @staticmethod
    async def room_exists(room_id):
        from asgiref.sync import sync_to_async
        return await sync_to_async(Room.objects.filter(id=room_id).exists)()
