from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.perks.models import SeasonEvent, StoreItem
from apps.rooms.models import Gift, Room, RoomParticipant, Seat
from apps.rooms.tests import make_user
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .models import RoomGame
from .services import normalise


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def fund(user, coins):
    Transaction.objects.create(user=user, type=Transaction.TYPE_BONUS, amount=coins)


@mock.patch("apps.games.services.broadcast_to_room")
class GameTests(TestCase):
    def setUp(self):
        self.host, self.p1, self.p2, self.out = make_user("hosty"), make_user("pone"), make_user("ptwo"), make_user("outsider")
        self.room = Room.objects.create(name="Games", category="talk", host=self.host, voice_room_name="vibra-g")
        for i in range(10):
            Seat.objects.create(room=self.room, position=i)
        for u in (self.host, self.p1, self.p2):
            RoomParticipant.objects.create(room=self.room, user=u)
        self.url = f"/api/games/rooms/{self.room.id}"

    def test_dice_for_anyone_inside_with_rate_limit(self, bc):
        res = client_for(self.p1).post(f"{self.url}/dice/")
        self.assertTrue(1 <= res.data["value"] <= 6)
        self.assertEqual(client_for(self.p1).post(f"{self.url}/dice/").status_code, 429)
        self.assertEqual(client_for(self.out).post(f"{self.url}/dice/").status_code, 403)

    def test_wheel_host_only_picks_someone(self, bc):
        self.assertEqual(client_for(self.p1).post(f"{self.url}/wheel/", {"mode": "truth"}).status_code, 403)
        res = client_for(self.host).post(f"{self.url}/wheel/", {"mode": "dare"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["kind"], "dare")
        self.assertIn(res.data["target"]["id"], [self.host.id, self.p1.id, self.p2.id])
        self.assertTrue(res.data["prompt"])

    def test_quiz_prize_split_between_right_answers(self, bc):
        fund(self.host, 1000)
        h = client_for(self.host)
        bad = h.post(f"{self.url}/start/", {"kind": "quiz", "question": "2+2?", "options": ["3", "4"], "correct": 5, "prize": 100}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(client_for(self.p1).post(f"{self.url}/start/", {"kind": "quiz"}, format="json").status_code, 403)
        res = h.post(f"{self.url}/start/", {"kind": "quiz", "question": "2+2?", "options": ["3", "4", "5"], "correct": 1,
                                             "prize": 301, "seconds": 20}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertNotIn("answer", res.data)                                  # never leaked
        gid = res.data["id"]
        self.assertEqual(get_balance(self.host), 1000 - 301)
        self.assertEqual(h.post(f"{self.url}/start/", {"kind": "quiz", "question": "x?", "options": ["a", "b"], "correct": 0}, format="json").status_code, 400)
        client_for(self.p1).post(f"{self.url}/answer/", {"game_id": gid, "answer": "1"}, format="json")
        client_for(self.p2).post(f"{self.url}/answer/", {"game_id": gid, "answer": "1"}, format="json")
        self.assertEqual(client_for(self.p2).post(f"{self.url}/answer/", {"game_id": gid, "answer": "0"}, format="json").status_code, 400)
        self.assertEqual(h.post(f"{self.url}/answer/", {"game_id": gid, "answer": "1"}, format="json").status_code, 400)
        RoomGame.objects.filter(id=gid).update(ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(client_for(self.p1).post(f"{self.url}/answer/", {"game_id": gid, "answer": "1"}, format="json").status_code, 400)
        done = client_for(self.p1).post(f"{self.url}/finish/", {"game_id": gid}, format="json").data
        self.assertEqual((done["status"], done["prize_each"], done["answer"], len(done["winners"])), ("done", 150, "4", 2))
        self.assertEqual((get_balance(self.p1), get_balance(self.p2), get_balance(self.host)), (150, 150, 1000 - 300))
        # settling twice pays nothing more
        client_for(self.p1).post(f"{self.url}/finish/", {"game_id": gid}, format="json")
        self.assertEqual(get_balance(self.p1), 150)

    def test_nobody_right_refunds_host(self, bc):
        fund(self.host, 500)
        gid = client_for(self.host).post(f"{self.url}/start/", {"kind": "quiz", "question": "Sky?", "options": ["blue", "green"],
                                                                 "correct": 0, "prize": 500}, format="json").data["id"]
        client_for(self.p1).post(f"{self.url}/answer/", {"game_id": gid, "answer": "1"}, format="json")
        RoomGame.objects.filter(id=gid).update(ends_at=timezone.now() - timedelta(seconds=1))
        client_for(self.p1).get(f"{self.url}/current/")
        self.assertEqual((get_balance(self.host), get_balance(self.p1)), (500, 0))

    def test_guess_the_song_first_right_wins(self, bc):
        fund(self.host, 200)
        self.assertEqual(normalise("  Tum Hi Ho!! "), "tum hi ho")
        gid = client_for(self.host).post(f"{self.url}/start/", {"kind": "guess", "answer": "Tum Hi Ho", "prize": 200, "seconds": 60},
                                         format="json").data["id"]
        p1 = client_for(self.p1)
        self.assertFalse(p1.post(f"{self.url}/answer/", {"game_id": gid, "answer": "kesariya"}, format="json").data["correct"])
        self.assertTrue(client_for(self.p2).post(f"{self.url}/answer/", {"game_id": gid, "answer": "tum hi ho"}, format="json").data["correct"])
        self.assertEqual(RoomGame.objects.get(id=gid).status, "done")
        self.assertEqual((get_balance(self.p2), get_balance(self.p1)), (200, 0))
        self.assertEqual(p1.post(f"{self.url}/answer/", {"game_id": gid, "answer": "tum hi ho"}, format="json").status_code, 400)

    def test_prize_needs_coins(self, bc):
        res = client_for(self.host).post(f"{self.url}/start/", {"kind": "guess", "answer": "x song", "prize": 50}, format="json")
        self.assertEqual(res.status_code, 400)


class EventTests(TestCase):
    def test_event_items_only_while_live_and_ranking(self):
        alice, bob = make_user("alice"), make_user("bobby")
        fund(alice, 50_000)
        now = timezone.now()
        SeasonEvent.objects.update(starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=5))
        live = SeasonEvent.objects.get(key="festival-of-lights")
        SeasonEvent.objects.filter(key="winter-wonderland").update(starts_at=now + timedelta(days=10), ends_at=now + timedelta(days=20))
        a = client_for(alice)
        store = {i["key"]: i for i in a.get("/api/perks/store/").data}
        self.assertIn("diya", store)
        self.assertNotIn("snowflake", store)                                  # not started yet
        self.assertEqual(store["diya"]["event"]["key"], live.key)
        self.assertEqual(a.post("/api/perks/store/buy/", {"item_id": store["diya"]["id"]}).status_code, 201)
        snow = StoreItem.objects.get(key="snowflake")
        self.assertEqual(a.post("/api/perks/store/buy/", {"item_id": snow.id}).status_code, 400)
        room = Room.objects.create(name="r", category="talk", host=bob, voice_room_name="vibra-ev")
        for u in (alice, bob):
            RoomParticipant.objects.create(room=room, user=u)
        with mock.patch("apps.wallet.views.broadcast_to_room"), mock.patch("apps.wallet.views.broadcast_to_everyone"):
            a.post("/api/wallet/gifts/send/", {"room_id": room.id, "recipient_id": bob.id,
                                               "gift_id": Gift.objects.get(name="Rose").id, "combo": 3}, format="json")
        events = a.get("/api/perks/events/").data
        self.assertEqual([(e["key"], e["live"]) for e in events], [("festival-of-lights", True), ("winter-wonderland", False)])
        self.assertEqual(events[0]["ranking"][0]["user"]["username"], "alice")
        # once it's over the item disappears from the store (unless owned)
        SeasonEvent.objects.filter(key=live.key).update(ends_at=now - timedelta(minutes=1))
        keys = {i["key"] for i in a.get("/api/perks/store/").data}
        self.assertIn("diya", keys)                                           # alice owns it
        self.assertNotIn("rangoli", keys)


class SocketHandlerTests(TestCase):
    """Every event the server broadcasts must have a consumer method, or Channels
    raises 'No handler for message type' and the socket dies."""

    def test_every_broadcast_has_a_handler(self):
        import pathlib
        import re

        from apps.rooms.consumers import RoomConsumer, UserConsumer
        root = pathlib.Path(__file__).resolve().parents[1]
        found = {"room": set(), "user": set(), "everyone": set()}
        pat = re.compile(r"broadcast_to_(room|user|everyone)\([^,]*?,?\s*\"([a-z_]+\.[a-z_]+)\"")
        for path in root.rglob("*.py"):
            if "tests" in path.name or "migrations" in path.parts:
                continue
            for kind, name in pat.findall(path.read_text(encoding="utf-8")):
                found[kind].add(name.replace(".", "_"))
        self.assertIn("game_wheel", found["room"])
        self.assertIn("family_message", found["user"])
        for name in found["room"]:
            self.assertTrue(hasattr(RoomConsumer, name), f"RoomConsumer has no handler for {name}")
        for name in found["user"] | found["everyone"]:
            self.assertTrue(hasattr(UserConsumer, name), f"UserConsumer has no handler for {name}")
