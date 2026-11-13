"""Phase 4: admin perks, room themes, room settings, slow mode, room levels."""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.perks.models import StoreItem
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .levels import level_info, room_level, seats_for
from .models import Gift, Message, Room, RoomParticipant, Seat
from .tests import make_user


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def fund(user, coins):
    Transaction.objects.create(user=user, type=Transaction.TYPE_BONUS, amount=coins)


def make_admin(name="boss"):
    u = make_user(name)
    u.is_superuser = True
    u.is_staff = True
    u.save()
    return u


def create_room(user, **extra):
    res = client_for(user).post("/api/rooms/", {"name": "Room", "category": "talk", **extra}, format="json")
    assert res.status_code == 201, res.content
    return Room.objects.get(id=res.data["id"])


class AdminPerkTests(TestCase):
    def test_admin_gets_vip5_badge_and_everything_free(self):
        boss = make_admin()
        c = client_for(boss)
        me = c.get("/api/auth/me/").data
        self.assertEqual((me["vip"]["tier"], me["is_admin"]), (5, True))
        store = c.get("/api/perks/store/").data
        self.assertTrue(all(i["owned_until"] and i["free_for_admin"] for i in store))
        dragon = StoreItem.objects.get(kind="mount", key="dragon")
        res = c.post("/api/perks/store/buy/", {"item_id": dragon.id})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(get_balance(boss), 0)                 # nothing charged
        self.assertEqual(c.get("/api/auth/me/").data["mount"], "dragon")
        gold = StoreItem.objects.get(kind="frame", key="gold")
        self.assertEqual(c.post("/api/perks/store/equip/", {"item_id": gold.id}).status_code, 200)
        self.assertEqual(c.get("/api/auth/me/").data["frame"], "gold")

    def test_normal_user_is_not_admin(self):
        alice = make_user("alice")
        me = client_for(alice).get("/api/auth/me/").data
        self.assertEqual((me["vip"]["tier"], me["is_admin"]), (0, False))

    def test_admin_has_no_live_room_limit(self):
        boss, alice = make_admin(), make_user("alice")
        for _ in range(5):
            create_room(boss)
        for _ in range(3):
            create_room(alice)
        res = client_for(alice).post("/api/rooms/", {"name": "Room", "category": "talk"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_admin_rooms_start_with_20_seats(self):
        self.assertEqual(Seat.objects.filter(room=create_room(make_admin())).count(), 20)
        self.assertEqual(Seat.objects.filter(room=create_room(make_user("alice"))).count(), 10)


class ThemeTests(TestCase):
    def setUp(self):
        self.host = make_user("hosty")
        self.room = create_room(self.host)
        self.c = client_for(self.host)
        self.rain = StoreItem.objects.get(kind="theme", key="rain")

    def test_theme_needs_ownership(self):
        res = self.c.post(f"/api/rooms/{self.room.id}/settings/", {"theme": "rain"}, format="json")
        self.assertEqual(res.status_code, 400)
        fund(self.host, 5000)
        self.assertEqual(self.c.post("/api/perks/store/buy/", {"item_id": self.rain.id}).status_code, 201)
        self.assertEqual(get_balance(self.host), 5000 - self.rain.price)
        self.assertEqual(self.c.get("/api/auth/me/").data["frame"], "")   # themes are not worn
        with mock.patch("apps.rooms.views.broadcast_to_room") as bc:
            res = self.c.post(f"/api/rooms/{self.room.id}/settings/", {"theme": "rain"}, format="json")
        self.assertEqual((res.status_code, res.data["theme"]), (200, "rain"))
        bc.assert_called_once()
        self.assertEqual(self.c.get(f"/api/rooms/{self.room.id}/").data["theme"], "rain")
        self.assertEqual(self.c.post("/api/perks/store/equip/", {"item_id": self.rain.id}).status_code, 400)

    def test_default_theme_is_free_and_admin_can_use_any(self):
        self.assertEqual(self.c.post(f"/api/rooms/{self.room.id}/settings/", {"theme": ""}, format="json").status_code, 200)
        boss_room = create_room(make_admin())
        res = client_for(boss_room.host).post(f"/api/rooms/{boss_room.id}/settings/", {"theme": "galaxy"}, format="json")
        self.assertEqual((res.status_code, res.data["theme"]), (200, "galaxy"))
        res = client_for(boss_room.host).post(f"/api/rooms/{boss_room.id}/settings/", {"theme": "nope"}, format="json")
        self.assertEqual(res.status_code, 400)


class RoomSettingsTests(TestCase):
    def setUp(self):
        self.host, self.guest = make_user("hosty"), make_user("guest")
        self.room = create_room(self.host)

    def test_only_host_changes_settings(self):
        res = client_for(self.guest).post(f"/api/rooms/{self.room.id}/settings/", {"announcement": "hi"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_announcement_welcome_and_validation(self):
        c = client_for(self.host)
        res = c.post(f"/api/rooms/{self.room.id}/settings/",
                     {"announcement": "  Be kind  ", "welcome_message": "Hello!", "slow_mode": 10}, format="json")
        self.assertEqual((res.data["announcement"], res.data["welcome_message"], res.data["slow_mode"]),
                         ("Be kind", "Hello!", 10))
        detail = c.get(f"/api/rooms/{self.room.id}/").data
        self.assertEqual((detail["announcement"], detail["slow_mode"]), ("Be kind", 10))
        self.assertEqual(c.post(f"/api/rooms/{self.room.id}/settings/", {"slow_mode": 7}, format="json").status_code, 400)

    def test_password_room(self):
        c = client_for(self.host)
        self.assertEqual(c.post(f"/api/rooms/{self.room.id}/settings/", {"password": "ab"}, format="json").status_code, 400)
        c.post(f"/api/rooms/{self.room.id}/settings/", {"password": "secret1"}, format="json")
        self.room.refresh_from_db()
        self.assertNotIn("secret1", self.room.password)          # stored hashed
        self.assertTrue(c.get("/api/rooms/").data[0]["has_password"])
        g = client_for(self.guest)
        res = g.post(f"/api/rooms/{self.room.id}/join/", {}, format="json")
        self.assertEqual((res.status_code, res.data["code"]), (403, "password_required"))
        res = g.post(f"/api/rooms/{self.room.id}/join/", {"password": "nope"}, format="json")
        self.assertEqual(res.data["code"], "password_wrong")
        self.assertEqual(g.post(f"/api/rooms/{self.room.id}/join/", {"password": "secret1"}, format="json").status_code, 200)
        # already inside: rejoining (reconnect) does not ask again
        self.assertEqual(g.post(f"/api/rooms/{self.room.id}/join/", {}, format="json").status_code, 200)
        # host and admin skip it
        self.assertEqual(c.post(f"/api/rooms/{self.room.id}/join/", {}, format="json").status_code, 200)
        self.assertEqual(client_for(make_admin()).post(f"/api/rooms/{self.room.id}/join/", {}, format="json").status_code, 200)
        c.post(f"/api/rooms/{self.room.id}/settings/", {"password": ""}, format="json")
        self.assertFalse(c.get(f"/api/rooms/{self.room.id}/").data["has_password"])

    def test_create_private_room_with_password(self):
        room = create_room(self.host, password="letmein")
        res = client_for(self.guest).post(f"/api/rooms/{room.id}/join/", {}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_slow_mode(self):
        c, g = client_for(self.host), client_for(self.guest)
        g.post(f"/api/rooms/{self.room.id}/join/", {}, format="json")
        c.post(f"/api/rooms/{self.room.id}/settings/", {"slow_mode": 30}, format="json")
        with mock.patch("apps.rooms.views.broadcast_to_room"):
            self.assertEqual(g.post(f"/api/rooms/{self.room.id}/messages/", {"text": "one"}, format="json").status_code, 201)
            res = g.post(f"/api/rooms/{self.room.id}/messages/", {"text": "two"}, format="json")
            self.assertEqual(res.status_code, 429)
            self.assertIn("Slow mode", res.data["detail"])
            # the host is never slowed down
            self.assertEqual(c.post(f"/api/rooms/{self.room.id}/messages/", {"text": "a"}, format="json").status_code, 201)
            self.assertEqual(c.post(f"/api/rooms/{self.room.id}/messages/", {"text": "b"}, format="json").status_code, 201)
        self.assertEqual(Message.objects.filter(room=self.room).count(), 3)


class RoomLevelTests(TestCase):
    def test_curve(self):
        self.assertEqual([room_level(x) for x in (0, 499, 500, 8000, 40500)], [1, 1, 2, 5, 10])
        self.assertEqual([seats_for(l) for l in (1, 4, 5, 9, 10, 30)], [10, 10, 15, 15, 20, 20])
        self.assertEqual(level_info(0)["next_seat_unlock_at"], 8000)

    def test_gifts_unlock_seats(self):
        host, fan = make_user("hosty"), make_user("fanny")
        room = create_room(host)
        RoomParticipant.objects.create(room=room, user=fan)
        fund(fan, 100_000)
        castle = Gift.objects.filter(cost__gte=5000).order_by("cost").first()
        combo = -(-8000 // castle.cost)   # enough for Lv5
        with mock.patch("apps.wallet.views.broadcast_to_room") as bc, mock.patch("apps.wallet.views.broadcast_to_everyone"):
            res = client_for(fan).post("/api/wallet/gifts/send/", {"room_id": room.id, "recipient_id": host.id,
                                                                   "gift_id": castle.id, "combo": combo}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Seat.objects.filter(room=room).count(), 15)
        events = [call.args[1] for call in bc.call_args_list]
        self.assertIn("room.level", events)
        detail = client_for(host).get(f"/api/rooms/{room.id}/").data
        self.assertEqual((detail["level"], detail["seat_count"], len(detail["seats"])), (5, 15, 15))
        # new seats work
        self.assertEqual(client_for(fan).post(f"/api/rooms/{room.id}/seats/14/take/").status_code, 200)
