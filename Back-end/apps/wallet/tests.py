import json
from concurrent.futures import ThreadPoolExecutor
from unittest import mock, skipUnless

import razorpay
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import Profile
from apps.rooms.models import Gift, Room, RoomParticipant

from .models import CoinPackage, PaymentOrder, Transaction
from .services import credit_paid_order, get_balance, send_gift

User = get_user_model()


def make_user(name):
    user = User.objects.create_user(username=name, password="S0me-Strong-Pass!")
    Profile.objects.create(user=user, username=name, avatar_url=f"https://example.com/{name}.svg")
    return user


class GiftTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_user("alice"), make_user("bobby")
        self.room = Room.objects.create(name="r", category="talk", host=self.bob, voice_room_name="vibra-t1")
        for u in (self.alice, self.bob):
            RoomParticipant.objects.create(room=self.room, user=u)
        self.gift = Gift.objects.create(name="Rose", emoji="R", cost=10)
        Transaction.objects.create(user=self.alice, type=Transaction.TYPE_PURCHASE, amount=100)
        self.client_a = APIClient()
        self.client_a.force_authenticate(self.alice)

    def send(self, **over):
        body = {"room_id": self.room.id, "recipient_id": self.bob.id, "gift_id": self.gift.id, "combo": 2}
        body.update(over)
        return self.client_a.post("/api/wallet/gifts/send/", body, format="json")

    def test_send_gift_moves_coins_and_broadcasts(self):
        with mock.patch("apps.wallet.views.broadcast_to_room") as bc:
            res = self.send()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["balance"], 80)
        self.assertEqual(get_balance(self.bob), 20)
        self.assertEqual(bc.call_args.args[:2], (self.room.id, "gift.sent"))

    def test_insufficient_balance_rejected(self):
        res = self.send(combo=11)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(get_balance(self.alice), 100)
        self.assertEqual(get_balance(self.bob), 0)

    def test_cannot_gift_self_or_non_participant_or_ended_room(self):
        self.assertEqual(self.send(recipient_id=self.alice.id).status_code, 400)
        carol = make_user("carol")
        self.assertEqual(self.send(recipient_id=carol.id).status_code, 400)
        Room.objects.filter(id=self.room.id).update(is_live=False)
        self.assertEqual(self.send().status_code, 400)
        self.assertEqual(get_balance(self.alice), 100)


class WebhookTests(TestCase):
    def setUp(self):
        self.user = make_user("alice")
        self.pkg = CoinPackage.objects.create(coins=500, price_inr="99.00")
        self.order = PaymentOrder.objects.create(user=self.user, package=self.pkg, razorpay_order_id="order_1")

    def post(self, payload, valid=True):
        body = json.dumps(payload)
        verify = mock.Mock(return_value=True)
        if not valid:
            verify.side_effect = razorpay.errors.SignatureVerificationError("bad")
        with mock.patch("apps.wallet.views.razorpay_client.utility.verify_webhook_signature", verify):
            return APIClient().post("/api/wallet/webhook/razorpay/", body, content_type="application/json")

    def paid(self, order_id="order_1"):
        return {"event": "order.paid", "payload": {"order": {"entity": {"id": order_id}}}}

    def test_credits_once_even_if_delivered_twice(self):
        self.assertEqual(self.post(self.paid()).status_code, 200)
        self.assertEqual(self.post(self.paid()).status_code, 200)
        self.assertEqual(get_balance(self.user), 500)
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 1)

    def test_service_is_idempotent(self):
        self.assertTrue(credit_paid_order("order_1"))
        self.assertFalse(credit_paid_order("order_1"))
        self.assertEqual(get_balance(self.user), 500)

    def test_bad_signature_unknown_order_and_malformed_payload(self):
        self.assertEqual(self.post(self.paid(), valid=False).status_code, 400)
        self.assertEqual(self.post(self.paid("nope")).status_code, 404)
        self.assertEqual(self.post({"event": "order.paid", "payload": {}}).status_code, 400)
        self.assertEqual(get_balance(self.user), 0)

    def test_other_events_ignored(self):
        self.assertEqual(self.post({"event": "payment.failed"}).status_code, 200)
        self.assertEqual(get_balance(self.user), 0)


@skipUnless(connection.vendor == "postgresql", "needs real row locking (PostgreSQL)")
class GiftConcurrencyTests(TransactionTestCase):
    def test_parallel_sends_cannot_overspend(self):
        alice, bob = make_user("alice"), make_user("bobby")
        room = Room.objects.create(name="r", category="talk", host=bob, voice_room_name="vibra-c1")
        for u in (alice, bob):
            RoomParticipant.objects.create(room=room, user=u)
        gift = Gift.objects.create(name="Rose", emoji="R", cost=10)
        Transaction.objects.create(user=alice, type=Transaction.TYPE_PURCHASE, amount=10)

        def attempt():
            try:
                send_gift(sender=alice, recipient=bob, gift=gift, room=room)
                return True
            except ValidationError:
                return False
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: attempt(), range(4)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(get_balance(alice), 0)
        self.assertEqual(get_balance(bob), 10)
