import shutil
import tempfile
from datetime import timedelta
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.levels import level_for, vip_for
from apps.accounts.models import Follow
from apps.rooms.models import Gift, Message, Room, RoomParticipant
from apps.rooms.tests import make_user
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .models import DailyCheckin, StoreItem
from .services import DAILY_REWARDS


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def fund(user, coins):
    Transaction.objects.create(user=user, type=Transaction.TYPE_BONUS, amount=coins)


class LevelTests(TestCase):
    def test_level_and_vip_curves(self):
        self.assertEqual([level_for(x) for x in (0, 99, 100, 400, 10_000)], [1, 1, 2, 3, 11])
        self.assertEqual(level_for(10**12), 99)
        self.assertEqual([vip_for(x) for x in (0, 999, 1000, 60_000, 2_000_000)], [0, 0, 1, 3, 5])

    def test_gifts_raise_wealth_and_charm_and_show_publicly(self):
        alice, bob = make_user("alice"), make_user("bobby")
        room = Room.objects.create(name="r", category="talk", host=bob, voice_room_name="vibra-lv")
        for u in (alice, bob):
            RoomParticipant.objects.create(room=room, user=u)
        fund(alice, 50_000)
        crown = Gift.objects.get(name="Crown")  # 2000
        with mock.patch("apps.wallet.views.broadcast_to_room"), mock.patch("apps.wallet.views.broadcast_to_everyone"):
            res = client_for(alice).post("/api/wallet/gifts/send/", {"room_id": room.id, "recipient_id": bob.id,
                                                                     "gift_id": crown.id, "combo": 1}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        me = client_for(alice).get("/api/auth/me/").data
        self.assertEqual((me["wealth"]["xp"], me["wealth"]["level"], me["vip"]["tier"], me["level"]), (2000, 5, 1, 5))
        seat_user = client_for(alice).get(f"/api/rooms/{room.id}/").data["host"]
        self.assertEqual((seat_user["charm_level"], seat_user["vip"]), (5, 0))


class StoreTests(TestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.c = client_for(self.alice)
        self.frame = StoreItem.objects.get(kind="frame", key="neon")
        self.mount = StoreItem.objects.get(kind="mount", key="car")

    def test_catalog_seeded(self):
        self.assertEqual(StoreItem.objects.filter(kind="frame", event__isnull=True).count(), 6)
        self.assertEqual(StoreItem.objects.filter(kind="mount", event__isnull=True).count(), 6)

    def test_buy_needs_coins_then_auto_equips_and_extends(self):
        self.assertEqual(self.c.post("/api/perks/store/buy/", {"item_id": self.frame.id}).status_code, 400)
        fund(self.alice, 20_000)
        res = self.c.post("/api/perks/store/buy/", {"item_id": self.frame.id})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(get_balance(self.alice), 20_000 - 500)
        me = self.c.get("/api/auth/me/").data
        self.assertEqual(me["frame"], "neon")
        first_until = res.data["owned_until"]
        again = self.c.post("/api/perks/store/buy/", {"item_id": self.frame.id})
        self.assertGreater(again.data["owned_until"], first_until)   # 7 more days
        listing = {i["key"]: i for i in self.c.get("/api/perks/store/").data}
        self.assertTrue(listing["neon"]["equipped"])
        self.assertIsNone(listing["gold"]["owned_until"])

    def test_equip_requires_ownership_and_unequip(self):
        self.assertEqual(self.c.post("/api/perks/store/equip/", {"item_id": self.mount.id}).status_code, 400)
        fund(self.alice, 20_000)
        self.c.post("/api/perks/store/buy/", {"item_id": self.mount.id})
        self.assertEqual(self.c.get("/api/auth/me/").data["mount"], "car")
        self.c.post("/api/perks/store/equip/", {"kind": "mount", "item_id": ""}, format="json")
        self.assertEqual(self.c.get("/api/auth/me/").data["mount"], "")

    def test_expired_items_stop_showing(self):
        fund(self.alice, 20_000)
        self.c.post("/api/perks/store/buy/", {"item_id": self.frame.id})
        p = self.alice.profile
        p.refresh_from_db()
        p.frame_until = timezone.now() - timedelta(seconds=1)
        p.save()
        self.assertEqual(self.c.get("/api/auth/me/").data["frame"], "")


class CheckinTests(TestCase):
    def test_streak_and_once_per_day(self):
        alice = make_user("alice")
        c = client_for(alice)
        self.assertFalse(c.get("/api/perks/checkin/").data["claimed_today"])
        res = c.post("/api/perks/checkin/")
        self.assertEqual((res.status_code, res.data["day"], res.data["coins"]), (201, 1, DAILY_REWARDS[0]))
        self.assertEqual(c.post("/api/perks/checkin/").status_code, 400)
        # pretend that claim was yesterday -> today continues the streak
        DailyCheckin.objects.filter(user=alice).update(day=timezone.localdate() - timedelta(days=1))
        self.assertEqual(c.post("/api/perks/checkin/").data["day"], 2)
        # a gap resets it
        DailyCheckin.objects.filter(user=alice).delete()
        DailyCheckin.objects.create(user=alice, day=timezone.localdate() - timedelta(days=5), streak=2, coins=80)
        self.assertEqual(c.post("/api/perks/checkin/").data["day"], 1)


class TaskTests(TestCase):
    def test_progress_and_claim(self):
        alice, bob = make_user("alice"), make_user("bobby")
        c = client_for(alice)
        tasks = {t["key"]: t for t in c.get("/api/perks/tasks/").data}
        self.assertFalse(tasks["follow"]["done"])
        self.assertEqual(c.post("/api/perks/tasks/", {"key": "follow"}).status_code, 400)
        Follow.objects.create(follower=alice, following=bob)
        res = c.post("/api/perks/tasks/", {"key": "follow"})
        self.assertEqual((res.status_code, res.data["coins"]), (201, 20))
        self.assertEqual(c.post("/api/perks/tasks/", {"key": "follow"}).status_code, 400)
        room = Room.objects.create(name="r", category="talk", host=bob, voice_room_name="vibra-tk")
        for i in range(5):
            Message.objects.create(room=room, user=alice, text=f"m{i}")
        tasks = {t["key"]: t for t in c.get("/api/perks/tasks/").data}
        self.assertEqual((tasks["chat"]["progress"], tasks["chat"]["done"], tasks["follow"]["claimed"]), (5, True, True))


class LeaderboardTests(TestCase):
    def test_rich_charm_rooms(self):
        alice, bob, carol = make_user("alice"), make_user("bobby"), make_user("carol")
        room = Room.objects.create(name="Top", category="talk", host=carol, voice_room_name="vibra-lb")
        for u in (alice, bob, carol):
            RoomParticipant.objects.create(room=room, user=u)
        fund(alice, 10_000)
        fund(bob, 10_000)
        rose, rocket = Gift.objects.get(name="Rose"), Gift.objects.get(name="Rocket")
        with mock.patch("apps.wallet.views.broadcast_to_room"), mock.patch("apps.wallet.views.broadcast_to_everyone"):
            client_for(alice).post("/api/wallet/gifts/send/", {"room_id": room.id, "recipient_id": carol.id, "gift_id": rocket.id, "combo": 1}, format="json")
            client_for(bob).post("/api/wallet/gifts/send/", {"room_id": room.id, "recipient_id": carol.id, "gift_id": rose.id, "combo": 5}, format="json")
        c = client_for(alice)
        rich = c.get("/api/perks/leaderboard/?board=rich&period=day").data
        self.assertEqual([(r["user"]["username"], r["score"]) for r in rich], [("alice", 1000), ("bobby", 50)])
        charm = c.get("/api/perks/leaderboard/?board=charm&period=week").data
        self.assertEqual((charm[0]["user"]["username"], charm[0]["score"]), ("carol", 1050))
        rooms = c.get("/api/perks/leaderboard/?board=rooms&period=month").data
        self.assertEqual((rooms[0]["room"]["name"], rooms[0]["score"]), ("Top", 1050))
        self.assertEqual(c.get("/api/perks/leaderboard/?board=nope").status_code, 400)


class RoomListTests(TestCase):
    def test_popular_and_following(self):
        alice, bob, carol = make_user("alice"), make_user("bobby"), make_user("carol")
        quiet = Room.objects.create(name="Quiet", category="talk", host=bob, voice_room_name="vibra-q")
        busy = Room.objects.create(name="Busy", category="talk", host=carol, voice_room_name="vibra-b")
        for u in (alice, bob, carol):
            RoomParticipant.objects.create(room=busy, user=u)
        c = client_for(alice)
        self.assertEqual([r["name"] for r in c.get("/api/rooms/?sort=popular").data][:2], ["Busy", "Quiet"])
        self.assertEqual([r["name"] for r in c.get("/api/rooms/").data][:2], ["Busy", "Quiet"])  # newest first
        Follow.objects.create(follower=alice, following=bob)
        self.assertEqual([r["name"] for r in c.get("/api/rooms/?scope=following").data], ["Quiet"])
        self.assertIn("gift_total", c.get("/api/rooms/").data[0])
        quiet.delete()


class AvatarUploadTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def png(self, w=800, h=500):
        buf = BytesIO()
        Image.new("RGB", (w, h), (200, 30, 120)).save(buf, "PNG")
        return SimpleUploadedFile("me.png", buf.getvalue(), content_type="image/png")

    def test_upload_crops_resizes_and_replaces(self):
        from pathlib import Path
        with override_settings(MEDIA_ROOT=Path(self.media)):
            alice = make_user("alice")
            c = client_for(alice)
            res = c.post("/api/auth/me/avatar/", {"avatar": self.png()}, format="multipart")
            self.assertEqual(res.status_code, 200, res.content)
            url = res.data["avatar_url"]
            self.assertIn("/media/avatars/", url)
            name = url.rsplit("/", 1)[-1]
            with Image.open(Path(self.media) / "avatars" / name) as img:
                self.assertEqual((img.size, img.format), ((320, 320), "JPEG"))
            served = c.get("/media/avatars/" + name)
            self.assertEqual(served.status_code, 200)
            served.close()   # release the file (Windows will not delete an open file)
            res2 = c.post("/api/auth/me/avatar/", {"avatar": self.png(300, 300)}, format="multipart")
            self.assertFalse((Path(self.media) / "avatars" / name).exists())   # old file removed
            self.assertNotEqual(res2.data["avatar_url"], url)

    def test_rejects_non_images_and_missing_file(self):
        alice = make_user("alice")
        c = client_for(alice)
        fake = SimpleUploadedFile("x.png", b"<script>alert(1)</script>", content_type="image/png")
        self.assertEqual(c.post("/api/auth/me/avatar/", {"avatar": fake}, format="multipart").status_code, 400)
        self.assertEqual(c.post("/api/auth/me/avatar/", {}, format="multipart").status_code, 400)
        self.assertEqual(c.get("/media/../config/settings.py").status_code, 404)
