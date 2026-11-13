import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Follow
from apps.notifications.models import Notification
from apps.rooms.models import Gift, Message, Room, RoomParticipant
from apps.rooms.tests import make_user
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .models import Bond, Family, ScheduledRoom


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def fund(user, coins):
    Transaction.objects.create(user=user, type=Transaction.TYPE_BONUS, amount=coins)


def make_admin(name="boss"):
    u = make_user(name)
    u.is_superuser = u.is_staff = True
    u.save()
    return u


class FamilyTests(TestCase):
    def setUp(self):
        self.alice, self.bob, self.carol = make_user("alice"), make_user("bobby"), make_user("carol")
        self.a = client_for(self.alice)

    def create(self, **kw):
        body = {"name": "Night Owls", "tag": "owl", "emblem": "moon", "description": "We talk late", **kw}
        return self.a.post("/api/social/families/", body, format="json")

    def test_create_join_badge_and_limits(self):
        res = self.create()
        self.assertEqual((res.status_code, res.data["tag"]), (201, "OWL"))
        fid = res.data["id"]
        self.assertEqual(self.create(name="Other").status_code, 400)                     # already in one
        self.assertEqual(client_for(self.bob).post("/api/social/families/", {"name": "night owls", "tag": "NO"}, format="json").status_code, 400)
        self.assertEqual(client_for(self.bob).post(f"/api/social/families/{fid}/join/").status_code, 200)
        me = client_for(self.bob).get("/api/auth/me/").data
        self.assertEqual((me["family"]["tag"], me["family"]["role"]), ("OWL", "member"))
        self.assertEqual(client_for(self.bob).get(f"/api/auth/users/alice/").data["family"]["name"], "Night Owls")
        detail = self.a.get(f"/api/social/families/{fid}/").data
        self.assertEqual((len(detail["members_list"]), detail["my_role"]), (2, "owner"))
        self.assertEqual(detail["members_list"][0]["user"]["family_tag"], "OWL")         # badge on public user

    def test_roles_kick_leave_and_ownership_passes_on(self):
        fid = self.create().data["id"]
        for u in (self.bob, self.carol):
            client_for(u).post(f"/api/social/families/{fid}/join/")
        b = client_for(self.bob)
        self.assertEqual(b.post(f"/api/social/families/{fid}/kick/", {"user_id": self.carol.id}).status_code, 403)
        self.a.post(f"/api/social/families/{fid}/role/", {"user_id": self.bob.id, "role": "elder"})
        self.assertEqual(b.post(f"/api/social/families/{fid}/kick/", {"user_id": self.carol.id}).status_code, 200)
        self.assertEqual(b.post(f"/api/social/families/{fid}/kick/", {"user_id": self.alice.id}).status_code, 403)
        self.carol.profile.refresh_from_db()
        self.assertEqual(self.carol.profile.family_tag, "")
        self.a.post(f"/api/social/families/{fid}/leave/")
        self.assertEqual(Family.objects.get(id=fid).owner_id, self.bob.id)                 # elder inherits
        b.post(f"/api/social/families/{fid}/leave/")
        self.assertFalse(Family.objects.filter(id=fid).exists())                          # last one out

    def test_chat_members_only(self):
        fid = self.create().data["id"]
        with mock.patch("apps.social.views.broadcast_to_user") as bc:
            self.assertEqual(self.a.post(f"/api/social/families/{fid}/chat/", {"text": "hi fam"}).status_code, 201)
        bc.assert_called_once()
        self.assertEqual(client_for(self.bob).get(f"/api/social/families/{fid}/chat/").status_code, 403)
        self.assertEqual(self.a.get(f"/api/social/families/{fid}/chat/").data[0]["text"], "hi fam")

    def test_weekly_family_ranking(self):
        fid = self.create().data["id"]
        client_for(self.bob).post(f"/api/social/families/{fid}/join/")
        room = Room.objects.create(name="r", category="talk", host=self.carol, voice_room_name="vibra-fam")
        for u in (self.alice, self.bob, self.carol):
            RoomParticipant.objects.create(room=room, user=u)
        fund(self.bob, 5000)
        rocket = Gift.objects.get(name="Rocket")
        with mock.patch("apps.wallet.views.broadcast_to_room"), mock.patch("apps.wallet.views.broadcast_to_everyone"):
            client_for(self.bob).post("/api/wallet/gifts/send/", {"room_id": room.id, "recipient_id": self.carol.id,
                                                                  "gift_id": rocket.id, "combo": 1}, format="json")
        board = self.a.get("/api/perks/leaderboard/?board=families&period=week").data
        self.assertEqual((board[0]["family"]["id"], board[0]["score"]), (fid, rocket.cost))
        self.assertEqual(self.a.get(f"/api/social/families/{fid}/").data["rank"], 1)


class BondTests(TestCase):
    def setUp(self):
        self.alice, self.bob, self.carol = make_user("alice"), make_user("bobby"), make_user("carol")
        fund(self.alice, 20_000)

    def test_cp_request_accept_shows_on_profiles(self):
        a = client_for(self.alice)
        res = a.post("/api/social/bonds/", {"user_id": self.bob.id, "kind": "cp"})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(get_balance(self.alice), 20_000 - Bond.COST["cp"])
        self.assertEqual(a.post("/api/social/bonds/", {"user_id": self.bob.id, "kind": "bff"}).status_code, 400)  # pending already
        b = client_for(self.bob)
        incoming = b.get("/api/social/bonds/").data["incoming"]
        self.assertEqual(incoming[0]["user"]["username"], "alice")
        self.assertTrue(Notification.objects.filter(user=self.bob, type="bond").exists())
        self.assertEqual(b.post(f"/api/social/bonds/requests/{incoming[0]['id']}/accept/").data["status"], "accepted")
        self.assertEqual(client_for(self.carol).get("/api/auth/users/bobby/").data["cp"]["username"], "alice")
        self.assertEqual(a.get(f"/api/social/bonds/of/{self.bob.id}/").data["with_me"], "cp")
        # one CP each
        fund(self.carol, 10_000)
        self.assertEqual(client_for(self.carol).post("/api/social/bonds/", {"user_id": self.alice.id, "kind": "cp"}).status_code, 400)
        # break
        a.post(f"/api/social/bonds/with/{self.bob.id}/break/")
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.bob.profile.cp_name, "")

    def test_decline_and_cancel_refund(self):
        a = client_for(self.alice)
        rid = a.post("/api/social/bonds/", {"user_id": self.bob.id, "kind": "bff"}).data["id"]
        self.assertEqual(client_for(self.bob).post(f"/api/social/bonds/requests/{rid}/decline/").status_code, 200)
        self.assertEqual(get_balance(self.alice), 20_000)
        rid = a.post("/api/social/bonds/", {"user_id": self.carol.id, "kind": "bff"}).data["id"]
        self.assertEqual(client_for(self.bob).post(f"/api/social/bonds/requests/{rid}/accept/").status_code, 403)
        a.post(f"/api/social/bonds/requests/{rid}/cancel/")
        self.assertEqual(get_balance(self.alice), 20_000)

    def test_needs_coins_but_admin_is_free(self):
        self.assertEqual(client_for(self.carol).post("/api/social/bonds/", {"user_id": self.bob.id, "kind": "cp"}).status_code, 400)
        boss = make_admin()
        self.assertEqual(client_for(boss).post("/api/social/bonds/", {"user_id": self.bob.id, "kind": "cp"}).status_code, 201)
        self.assertEqual(get_balance(boss), 0)


class VisitorAndFriendsTests(TestCase):
    def test_visitors(self):
        alice, bob = make_user("alice"), make_user("bobby")
        b = client_for(bob)
        b.get("/api/auth/users/alice/")
        b.get("/api/auth/users/alice/")
        client_for(alice).get("/api/auth/users/alice/")                    # own views don't count
        a = client_for(alice)
        data = a.get("/api/social/visitors/").data
        self.assertEqual((data["new"], data["visitors"][0]["count"], data["visitors"][0]["user"]["username"]), (1, 2, "bobby"))
        self.assertEqual(a.get("/api/auth/me/").data["new_visitors"], 1)
        a.post("/api/social/visitors/")
        self.assertEqual(a.get("/api/social/visitors/").data["new"], 0)
        self.assertIsNone(b.get("/api/auth/users/alice/").data["new_visitors"])  # private

    def test_friends_live(self):
        alice, bob, carol = make_user("alice"), make_user("bobby"), make_user("carol")
        room = Room.objects.create(name="Chill", category="talk", host=carol, voice_room_name="vibra-fl")
        RoomParticipant.objects.create(room=room, user=bob)
        RoomParticipant.objects.create(room=room, user=carol)
        Follow.objects.create(follower=alice, following=bob)
        rows = client_for(alice).get("/api/social/friends-live/").data
        self.assertEqual([(r["user"]["username"], r["room"]["name"]) for r in rows], [("bobby", "Chill")])


class VoiceTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def clip(self, data=b"\x1aE\xdf\xa3" + b"\x00" * 200):
        return SimpleUploadedFile("v.webm", data, content_type="audio/webm")

    def test_voice_dm_and_room_message(self):
        with override_settings(MEDIA_ROOT=Path(self.media)):
            alice, bob = make_user("alice"), make_user("bobby")
            a = client_for(alice)
            self.assertEqual(a.post("/api/social/voice/", {"audio": SimpleUploadedFile("x.webm", b"<html>", content_type="audio/webm")},
                                    format="multipart").status_code, 400)
            res = a.post("/api/social/voice/", {"audio": self.clip(), "seconds": "4.4"}, format="multipart")
            self.assertEqual((res.status_code, res.data["seconds"]), (201, 4), res.content)
            vid = res.data["id"]
            served = a.get("/media/voice/" + res.data["url"].rsplit("/", 1)[-1])
            self.assertEqual(served.status_code, 200)
            served.close()
            with mock.patch("apps.dms.views.broadcast_to_user"):
                dm = a.post(f"/api/dms/{bob.id}/", {"voice_id": vid}, format="json")
            self.assertEqual((dm.status_code, dm.data["voice"]["seconds"]), (201, 4), dm.content)
            self.assertEqual(client_for(bob).get(f"/api/dms/{alice.id}/").data["messages"][0]["voice"]["id"], vid)
            # someone else's clip can't be reused
            self.assertEqual(client_for(bob).post(f"/api/dms/{alice.id}/", {"voice_id": vid}, format="json").status_code, 400)
            # empty DM still rejected
            self.assertEqual(a.post(f"/api/dms/{bob.id}/", {"text": "  "}, format="json").status_code, 400)
            room = Room.objects.create(name="r", category="talk", host=bob, voice_room_name="vibra-vo")
            RoomParticipant.objects.create(room=room, user=alice)
            with mock.patch("apps.rooms.views.broadcast_to_room"):
                msg = a.post(f"/api/rooms/{room.id}/messages/", {"voice_id": vid}, format="json")
                self.assertEqual(msg.status_code, 201, msg.content)
                self.assertEqual(a.post(f"/api/rooms/{room.id}/messages/", {"text": ""}, format="json").status_code, 400)
                self.assertEqual(a.post(f"/api/rooms/{room.id}/messages/", {"text": "[sticker:love]"}, format="json").status_code, 201)
            self.assertEqual(Message.objects.filter(room=room, voice_id=vid).count(), 1)


class ScheduledRoomTests(TestCase):
    def test_schedule_remind_notify_and_go_live(self):
        host, fan = make_user("hosty"), make_user("fanny")
        h, f = client_for(host), client_for(fan)
        soon = (timezone.now() + timedelta(minutes=2)).isoformat()
        self.assertEqual(h.post("/api/social/scheduled/", {"title": "Talk", "category": "talk", "starts_at": soon}, format="json").status_code, 400)
        later = (timezone.now() + timedelta(minutes=10)).isoformat()
        res = h.post("/api/social/scheduled/", {"title": "Late talk", "category": "music", "starts_at": later}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        sid = res.data["id"]
        self.assertTrue(f.post(f"/api/social/scheduled/{sid}/remind/").data["reminded"])
        listing = f.get("/api/social/scheduled/").data
        self.assertEqual((listing[0]["reminded"], listing[0]["reminders"]), (True, 1))
        self.assertEqual(f.post(f"/api/social/scheduled/{sid}/start/").status_code, 403)
        # the timer sends "starting soon" once it's within 5 minutes
        ScheduledRoom.objects.filter(id=sid).update(starts_at=timezone.now() + timedelta(minutes=4))
        with mock.patch("apps.rooms.realtime._broadcast"):
            call_command("cleanup_stale_rooms", stdout=open("nul" if __import__("os").name == "nt" else "/dev/null", "w"))
        self.assertTrue(Notification.objects.filter(user=fan, type="scheduled").exists())
        res = h.post(f"/api/social/scheduled/{sid}/start/")
        self.assertEqual(res.status_code, 201, res.content)
        room = Room.objects.get(id=res.data["room_id"])
        self.assertEqual((room.name, room.category, room.seats.count()), ("Late talk", "music", 10))
        self.assertTrue(Notification.objects.filter(user=fan, type="live", room=room).exists())
        self.assertEqual(f.get("/api/social/scheduled/").data, [])                # no longer upcoming
