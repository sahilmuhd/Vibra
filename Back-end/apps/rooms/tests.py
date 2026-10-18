from unittest import mock

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Profile
from config.jwt_auth_middleware import JWTAuthMiddleware
from config.routing import websocket_urlpatterns

from .models import HandRaise, Message, Room, RoomParticipant, Seat

User = get_user_model()


def make_user(name):
    user = User.objects.create_user(username=name, password="S0me-Strong-Pass!")
    Profile.objects.create(user=user, username=name, avatar_url=f"https://example.com/{name}.svg")
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class RoomBase(TestCase):
    def setUp(self):
        self.host = make_user("hosty")
        self.alice = make_user("alice")
        self.bob = make_user("bobby")
        self.host_c, self.alice_c, self.bob_c = map(client_for, (self.host, self.alice, self.bob))

    def create_room(self, client=None, **overrides):
        payload = {"name": "Late Night", "category": "talk", "description": "chill"}
        payload.update(overrides)
        return (client or self.host_c).post("/api/rooms/", payload, format="json")


class RoomCreateTests(RoomBase):
    def test_requires_auth(self):
        self.assertEqual(APIClient().post("/api/rooms/", {"name": "x", "category": "talk"}, format="json").status_code, 401)

    def test_create_builds_seats_seats_host_and_registers_participant(self):
        res = self.create_room()
        self.assertEqual(res.status_code, 201, res.content)
        room = Room.objects.get(id=res.data["id"])
        self.assertEqual(room.host, self.host)
        self.assertEqual(room.seats.count(), 9)
        seat0 = room.seats.get(position=0)
        self.assertEqual(seat0.user, self.host)
        self.assertFalse(seat0.is_muted)
        self.assertEqual(room.seats.exclude(user=None).count(), 1)
        self.assertTrue(RoomParticipant.objects.filter(room=room, user=self.host).exists())
        self.assertEqual(res.data["online_count"], 1)
        self.assertTrue(room.voice_room_name.startswith("vibra-"))

    def test_client_cannot_set_liveness_or_thumbnail(self):
        res = self.create_room(is_live=False, thumbnail_seed="evil", seat_count=500)
        self.assertEqual(res.status_code, 201, res.content)
        room = Room.objects.get(id=res.data["id"])
        self.assertTrue(room.is_live)
        self.assertEqual(room.thumbnail_seed, "")
        self.assertEqual(room.seats.count(), 9)

    def test_validation(self):
        self.assertEqual(self.create_room(category="nonsense").status_code, 400)
        self.assertEqual(self.create_room(name="a").status_code, 400)
        self.assertEqual(self.create_room(name="   ").status_code, 400)
        self.assertEqual(self.create_room(name="x" * 81).status_code, 400)
        self.assertEqual(Room.objects.count(), 0)


class RoomListTests(RoomBase):
    def test_lists_only_live_rooms_newest_first_and_filters_by_category(self):
        a = self.create_room(name="Music One", category="music").data["id"]
        b = self.create_room(name="Talk One", category="talk").data["id"]
        Room.objects.filter(id=a).update(is_live=True)
        dead = self.create_room(name="Ended", category="talk").data["id"]
        Room.objects.filter(id=dead).update(is_live=False)

        ids = [r["id"] for r in self.alice_c.get("/api/rooms/").data]
        self.assertEqual(ids, [b, a])
        music = [r["id"] for r in self.alice_c.get("/api/rooms/?category=Music").data]
        self.assertEqual(music, [a])

    def test_online_count_includes_listeners(self):
        rid = self.create_room().data["id"]
        self.alice_c.post(f"/api/rooms/{rid}/join/")
        self.bob_c.post(f"/api/rooms/{rid}/join/")
        listing = self.alice_c.get("/api/rooms/").data
        self.assertEqual(listing[0]["online_count"], 3)  # host + 2 listeners
        self.assertEqual(Seat.objects.filter(room_id=rid).exclude(user=None).count(), 1)  # only host is on a seat


class JoinLeaveTests(RoomBase):
    def setUp(self):
        super().setUp()
        self.rid = self.create_room().data["id"]

    def test_join_returns_snapshot_and_is_idempotent(self):
        first = self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(len(first.data["seats"]), 9)
        self.assertEqual(first.data["seats"][0]["user"]["username"], "hosty")
        self.assertEqual(first.data["online_count"], 2)
        again = self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(RoomParticipant.objects.filter(room_id=self.rid, user=self.alice).count(), 1)

    def test_join_broadcasts_presence_only_on_first_join(self):
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            self.alice_c.post(f"/api/rooms/{self.rid}/join/")
            self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        events = [c.args[1] for c in bc.call_args_list]
        self.assertEqual(events, ["presence.update"])

    def test_join_unknown_room_is_404_and_ended_room_is_410(self):
        self.assertEqual(self.alice_c.post("/api/rooms/999999/join/").status_code, 404)
        Room.objects.filter(id=self.rid).update(is_live=False)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/join/").status_code, 410)

    def test_join_requires_auth(self):
        self.assertEqual(APIClient().post(f"/api/rooms/{self.rid}/join/").status_code, 401)

    def test_leave_frees_seat_hand_raise_and_participation(self):
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.alice_c.post(f"/api/rooms/{self.rid}/seats/3/take/")
        self.alice_c.post(f"/api/rooms/{self.rid}/hand-raise/")
        self.assertEqual(Seat.objects.get(room_id=self.rid, position=3).user, self.alice)

        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.alice_c.post(f"/api/rooms/{self.rid}/leave/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["released_seats"], [3])
        seat = Seat.objects.get(room_id=self.rid, position=3)
        self.assertIsNone(seat.user)
        self.assertTrue(seat.is_muted)
        self.assertFalse(HandRaise.objects.filter(room_id=self.rid, user=self.alice).exists())
        self.assertFalse(RoomParticipant.objects.filter(room_id=self.rid, user=self.alice).exists())
        self.assertEqual([c.args[1] for c in bc.call_args_list], ["seat.update", "presence.update"])
        # host untouched
        self.assertEqual(Seat.objects.get(room_id=self.rid, position=0).user, self.host)

    def test_leave_is_idempotent_and_silent_when_not_in_room(self):
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.bob_c.post(f"/api/rooms/{self.rid}/leave/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["released_seats"], [])
        bc.assert_not_called()

    def test_leave_works_for_ended_room(self):
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        Room.objects.filter(id=self.rid).update(is_live=False)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/leave/").status_code, 200)
        self.assertFalse(RoomParticipant.objects.filter(room_id=self.rid, user=self.alice).exists())


class MessageTests(RoomBase):
    def setUp(self):
        super().setUp()
        self.rid = self.create_room().data["id"]
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")

    def url(self, rid=None):
        return f"/api/rooms/{rid or self.rid}/messages/"

    def test_frontend_payload_without_room_field_is_accepted(self):
        # Regression: `room` used to be required in the body, so this was a 400.
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.alice_c.post(self.url(), {"text": "hello", "reply_to": None}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["user"]["username"], "alice")
        self.assertEqual(res.data["room"], self.rid)
        bc.assert_called_once()
        self.assertEqual(bc.call_args.args[:2], (self.rid, "message.new"))

    def test_must_join_before_posting(self):
        res = self.bob_c.post(self.url(), {"text": "sneaky"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_blank_and_whitespace_rejected(self):
        for text in ("", "   ", "\n\t"):
            self.assertEqual(self.alice_c.post(self.url(), {"text": text}, format="json").status_code, 400, repr(text))

    def test_too_long_rejected(self):
        self.assertEqual(self.alice_c.post(self.url(), {"text": "x" * 501}, format="json").status_code, 400)

    def test_nonexistent_room_is_404_not_500(self):
        self.assertEqual(self.alice_c.post(self.url(999999), {"text": "hi"}, format="json").status_code, 404)
        self.assertEqual(self.alice_c.get(self.url(999999)).status_code, 404)

    def test_ended_room_rejects_new_messages(self):
        Room.objects.filter(id=self.rid).update(is_live=False)
        self.assertEqual(self.alice_c.post(self.url(), {"text": "hi"}, format="json").status_code, 403)

    def test_client_cannot_redirect_message_to_another_room(self):
        other = self.create_room(name="Other room").data["id"]
        res = self.alice_c.post(self.url(), {"text": "hi", "room": other}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Message.objects.get(id=res.data["id"]).room_id, self.rid)

    def test_reply_to_must_be_in_same_room(self):
        other = self.create_room(name="Other room").data["id"]
        foreign = Message.objects.create(room_id=other, user=self.host, text="elsewhere")
        res = self.alice_c.post(self.url(), {"text": "hi", "reply_to": foreign.id}, format="json")
        self.assertEqual(res.status_code, 400)
        local = Message.objects.create(room_id=self.rid, user=self.host, text="here")
        ok = self.alice_c.post(self.url(), {"text": "hi", "reply_to": local.id}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_list_is_newest_first_capped_at_50(self):
        for i in range(55):
            Message.objects.create(room_id=self.rid, user=self.alice, text=f"m{i}")
        data = self.alice_c.get(self.url()).data
        self.assertEqual(len(data), 50)
        self.assertEqual(data[0]["text"], "m54")
        self.assertEqual(data[-1]["text"], "m5")


class RealtimeFailureTests(RoomBase):
    def test_redis_outage_does_not_500_a_committed_change(self):
        rid = self.create_room().data["id"]

        class Boom:
            async def group_send(self, *a, **k):
                raise ConnectionError("redis down")

        with mock.patch("apps.rooms.realtime.get_channel_layer", return_value=Boom()):
            res = self.alice_c.post(f"/api/rooms/{rid}/join/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(RoomParticipant.objects.filter(room_id=rid, user=self.alice).exists())


class WebSocketTests(TransactionTestCase):
    """Async + threads need TransactionTestCase (no wrapping transaction)."""

    def setUp(self):
        self.host = make_user("hosty")
        self.room = Room.objects.create(name="WS room", category="talk", host=self.host, voice_room_name="vibra-wstest")
        self.app = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        self.path = f"/ws/rooms/{self.room.id}/"

    def comm(self, token=None):
        suffix = f"?token={token}" if token else ""
        return WebsocketCommunicator(self.app, self.path + suffix)

    async def test_unauthenticated_socket_is_rejected_and_cannot_spoof_presence(self):
        token = str(AccessToken.for_user(self.host))
        legit = self.comm(token)
        connected, _ = await legit.connect()
        self.assertTrue(connected)
        joined = await legit.receive_json_from()
        self.assertEqual((joined["event"], joined["action"]), ("presence_update", "joined"))

        for bad in (self.comm(), self.comm("not-a-jwt")):
            ok, _ = await bad.connect()
            self.assertFalse(ok)
            await bad.disconnect()
        # Before the fix a rejected socket broadcast {"user_id": null, "action": "left"}.
        self.assertTrue(await legit.receive_nothing(timeout=0.3))
        await legit.disconnect()

    async def test_non_object_frames_do_not_crash_consumer(self):
        legit = self.comm(str(AccessToken.for_user(self.host)))
        await legit.connect()
        await legit.receive_json_from()
        await legit.send_json_to([1, 2, 3])
        self.assertTrue(await legit.receive_nothing(timeout=0.2))
        await legit.disconnect()

    async def test_unknown_room_is_rejected(self):
        comm = WebsocketCommunicator(self.app, f"/ws/rooms/999999/?token={AccessToken.for_user(self.host)}")
        connected, _ = await comm.connect()
        self.assertFalse(connected)


class HostModerationTests(RoomBase):
    def setUp(self):
        super().setUp()
        self.rid = self.create_room().data["id"]
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.alice_c.post(f"/api/rooms/{self.rid}/seats/1/take/")

    def test_end_room_by_host_clears_participants_and_seats(self):
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.host_c.post(f"/api/rooms/{self.rid}/end/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["ended"])
        room = Room.objects.get(id=self.rid)
        self.assertFalse(room.is_live)
        self.assertEqual(Seat.objects.filter(room_id=self.rid).exclude(user=None).count(), 0)
        self.assertEqual(RoomParticipant.objects.filter(room_id=self.rid).count(), 0)
        bc.assert_called_once_with(self.rid, "room.ended", {"room_id": self.rid})

    def test_end_room_forbidden_for_non_host(self):
        res = self.alice_c.post(f"/api/rooms/{self.rid}/end/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Room.objects.get(id=self.rid).is_live)

    def test_force_mute_by_host(self):
        # Alice is in seat 1
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.host_c.post(f"/api/rooms/{self.rid}/seats/1/force-mute/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Seat.objects.get(room_id=self.rid, position=1).is_muted)
        bc.assert_called_once_with(self.rid, "seat.mute", {"position": 1, "is_muted": True, "forced": True})

        # Non-host cannot force mute
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/0/force-mute/").status_code, 403)

    def test_lock_seat_evicts_occupant(self):
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.host_c.post(f"/api/rooms/{self.rid}/seats/1/lock/")
        self.assertEqual(res.status_code, 200)
        seat = Seat.objects.get(room_id=self.rid, position=1)
        self.assertTrue(seat.is_locked)
        self.assertIsNone(seat.user)  # Alice was evicted
        events = [c.args[1] for c in bc.call_args_list]
        self.assertIn("seat.lock", events)
        self.assertIn("seat.update", events)

    def test_kick_participant_frees_seat_and_removes(self):
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.host_c.post(f"/api/rooms/{self.rid}/kick/", {"user_id": self.alice.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["kicked"])
        self.assertFalse(RoomParticipant.objects.filter(room_id=self.rid, user=self.alice).exists())
        self.assertIsNone(Seat.objects.get(room_id=self.rid, position=1).user)

        # Host cannot kick themselves
        res_self = self.host_c.post(f"/api/rooms/{self.rid}/kick/", {"user_id": self.host.id}, format="json")
        self.assertEqual(res_self.status_code, 400)

    def test_raise_hand_toggle_and_delete(self):
        # 1. Raise hand
        r1 = self.alice_c.post(f"/api/rooms/{self.rid}/hand-raise/")
        self.assertEqual(r1.status_code, 201)
        self.assertTrue(r1.data["raised"])
        self.assertTrue(HandRaise.objects.filter(room_id=self.rid, user=self.alice).exists())

        # 2. Call again -> toggles off
        r2 = self.alice_c.post(f"/api/rooms/{self.rid}/hand-raise/")
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.data["raised"])
        self.assertFalse(HandRaise.objects.filter(room_id=self.rid, user=self.alice).exists())

        # 3. Raise and then DELETE
        self.alice_c.post(f"/api/rooms/{self.rid}/hand-raise/")
        r3 = self.alice_c.delete(f"/api/rooms/{self.rid}/hand-raise/")
        self.assertEqual(r3.status_code, 200)
        self.assertFalse(HandRaise.objects.filter(room_id=self.rid, user=self.alice).exists())

