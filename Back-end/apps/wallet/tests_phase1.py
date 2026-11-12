"""Gift catalog, welcome coins, room gift total and the global gift banner."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.rooms.models import Gift, Room, RoomParticipant
from apps.rooms.tests import make_user

from .models import Transaction
from .services import get_balance


class GiftCatalogTests(TestCase):
    def test_catalog_is_seeded_with_tiers(self):
        gifts = {g.name: g for g in Gift.objects.all()}
        self.assertGreaterEqual(len(gifts), 14)
        self.assertEqual(gifts["Rose"].animation_key, "")
        self.assertEqual(gifts["Bouquet"].animation_key, "burst")
        self.assertEqual(gifts["Rocket"].animation_key, "rocket")


class WelcomeCoinsTests(TestCase):
    @override_settings(WELCOME_COINS=1000)
    def test_new_accounts_get_welcome_coins_once(self):
        user = get_user_model().objects.create_user(username="newbie", password="S0me-Strong-Pass!")
        self.assertEqual(get_balance(user), 1000)
        user.save()  # later saves must not pay again
        self.assertEqual(Transaction.objects.filter(user=user, type=Transaction.TYPE_BONUS).count(), 1)

    @override_settings(WELCOME_COINS=1000)
    def test_guest_login_gets_coins_too(self):
        res = APIClient().post("/api/auth/guest/")
        user = get_user_model().objects.get(id=res.data["user"]["id"])
        self.assertEqual(get_balance(user), 1000)

    def test_grant_coins_command(self):
        a, b = make_user("alice"), make_user("bobby")
        call_command("grant_coins", "500", "--user", "alice")
        self.assertEqual((get_balance(a), get_balance(b)), (500, 0))
        call_command("grant_coins", "100", "--all")
        self.assertEqual((get_balance(a), get_balance(b)), (600, 100))


class GiftTotalAndBroadcastTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_user("alice"), make_user("bobby")
        self.room = Room.objects.create(name="r", category="talk", host=self.bob, voice_room_name="vibra-p1")
        for u in (self.alice, self.bob):
            RoomParticipant.objects.create(room=self.room, user=u)
        Transaction.objects.create(user=self.alice, type=Transaction.TYPE_BONUS, amount=50000)
        self.c = APIClient()
        self.c.force_authenticate(self.alice)

    def send(self, gift_name, combo=1):
        gift = Gift.objects.filter(name=gift_name).first()
        return self.c.post("/api/wallet/gifts/send/", {
            "room_id": self.room.id, "recipient_id": self.bob.id, "gift_id": gift.id, "combo": combo,
        }, format="json")

    @override_settings(GLOBAL_GIFT_MIN=2000)
    def test_small_gift_stays_in_room_big_gift_goes_global(self):
        with mock.patch("apps.wallet.views.broadcast_to_room") as room_bc, \
             mock.patch("apps.wallet.views.broadcast_to_everyone") as global_bc:
            self.assertEqual(self.send("Rose", combo=3).status_code, 200)
            global_bc.assert_not_called()
            payload = room_bc.call_args.args[2]
            self.assertEqual((payload["recipient_name"], payload["gift_cost"], payload["combo"]), ("bobby", 10, 3))
            self.assertEqual(self.send("Crown").status_code, 200)
            self.assertEqual(global_bc.call_args.args[0], "gift.global")
            self.assertEqual(global_bc.call_args.args[1]["room_name"], "r")
            self.assertEqual(global_bc.call_args.args[1]["animation_key"], "crown")

    def test_room_detail_reports_gift_total(self):
        with mock.patch("apps.wallet.views.broadcast_to_room"), mock.patch("apps.wallet.views.broadcast_to_everyone"):
            self.send("Rose", combo=3)    # 30
            self.send("Rocket")           # 1000
        detail = self.c.get(f"/api/rooms/{self.room.id}/").data
        self.assertEqual(detail["gift_total"], 1030)
        self.assertEqual(detail["online_count"], 2)  # the subquery must not multiply counts
