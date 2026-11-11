"""Moderators, reports, blocks, follows and notifications."""
from apps.accounts.models import Block, Follow
from apps.notifications.models import Notification

from .models import Message, Report, RoomModerator, Seat
from .tests import RoomBase


class ModeratorTests(RoomBase):
    def setUp(self):
        super().setUp()
        self.rid = self.create_room().data["id"]
        for c in (self.alice_c, self.bob_c):
            c.post(f"/api/rooms/{self.rid}/join/")
        self.bob_c.post(f"/api/rooms/{self.rid}/seats/2/take/")

    def promote(self, user, on=True, client=None):
        return (client or self.host_c).post(
            f"/api/rooms/{self.rid}/moderators/", {"user_id": user.id, "is_moderator": on}, format="json"
        )

    def test_only_host_appoints_and_mod_ids_are_in_room_detail(self):
        self.assertEqual(self.promote(self.alice, client=self.bob_c).status_code, 403)
        res = self.promote(self.alice)
        self.assertEqual(res.data["moderator_ids"], [self.alice.id])
        detail = self.alice_c.get(f"/api/rooms/{self.rid}/")
        self.assertEqual(detail.data["moderator_ids"], [self.alice.id])
        self.promote(self.alice, on=False)
        self.assertFalse(RoomModerator.objects.exists())

    def test_moderator_can_mute_lock_and_kick_listeners(self):
        self.promote(self.alice)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/2/force-mute/").status_code, 200)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/5/lock/").status_code, 200)
        res = self.alice_c.post(f"/api/rooms/{self.rid}/kick/", {"user_id": self.bob.id}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_moderator_cannot_touch_host_or_other_mods_or_end_room(self):
        self.promote(self.alice)
        self.promote(self.bob)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/0/force-mute/").status_code, 403)
        res = self.alice_c.post(f"/api/rooms/{self.rid}/kick/", {"user_id": self.bob.id}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/end/").status_code, 403)

    def test_non_participant_cannot_be_promoted(self):
        from .tests import make_user

        stranger = make_user("strngr")
        self.assertEqual(self.promote(stranger).status_code, 400)


class ReportTests(RoomBase):
    def test_report_room_and_user(self):
        rid = self.create_room().data["id"]
        res = self.alice_c.post("/api/reports/", {"room_id": rid, "user_id": self.host.id,
                                                   "reason": "abuse", "details": "shouting"}, format="json")
        self.assertEqual(res.status_code, 201)
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.reported_user, report.room_id), (self.alice, self.host, rid))

    def test_report_validation(self):
        self.assertEqual(self.alice_c.post("/api/reports/", {"reason": "abuse"}, format="json").status_code, 400)
        self.assertEqual(self.alice_c.post("/api/reports/", {"user_id": self.bob.id, "reason": "nope"},
                                           format="json").status_code, 400)
        self.assertEqual(self.alice_c.post("/api/reports/", {"user_id": self.alice.id, "reason": "spam"},
                                           format="json").status_code, 400)


class BlockFollowTests(RoomBase):
    def test_follow_unfollow_and_profile_flags(self):
        res = self.alice_c.post(f"/api/auth/users/{self.bob.id}/follow/")
        self.assertEqual((res.status_code, res.data["followers_count"]), (200, 1))
        profile = self.alice_c.get("/api/auth/users/bobby/")
        self.assertTrue(profile.data["is_following"])
        self.alice_c.delete(f"/api/auth/users/{self.bob.id}/follow/")
        self.assertFalse(Follow.objects.exists())
        self.assertEqual(self.alice_c.post(f"/api/auth/users/{self.alice.id}/follow/").status_code, 400)

    def test_block_removes_follows_hides_messages_and_bars_from_hosted_rooms(self):
        Follow.objects.create(follower=self.host, following=self.alice)
        Follow.objects.create(follower=self.alice, following=self.host)
        rid = self.create_room().data["id"]
        self.alice_c.post(f"/api/rooms/{rid}/join/")
        Message.objects.create(room_id=rid, user=self.alice, text="rude")

        self.assertEqual(self.host_c.post(f"/api/auth/users/{self.alice.id}/block/").status_code, 200)
        self.assertFalse(Follow.objects.exists())
        texts = [m["text"] for m in self.host_c.get(f"/api/rooms/{rid}/messages/").data]
        self.assertNotIn("rude", texts)

        self.alice_c.post(f"/api/rooms/{rid}/leave/")
        self.assertEqual(self.alice_c.post(f"/api/rooms/{rid}/join/").status_code, 403)
        self.assertEqual(self.alice_c.post(f"/api/auth/users/{self.host.id}/follow/").status_code, 403)

        listed = self.host_c.get("/api/auth/blocks/").data
        self.assertEqual([u["id"] for u in listed], [self.alice.id])
        self.host_c.delete(f"/api/auth/users/{self.alice.id}/block/")
        self.assertFalse(Block.objects.exists())


class NotificationTests(RoomBase):
    def test_follow_and_going_live_notify_then_mark_read(self):
        self.alice_c.post(f"/api/auth/users/{self.host.id}/follow/")
        self.create_room(name="Night Talk")

        self.assertEqual(self.host_c.get("/api/notifications/unread-count/").data["unread"], 1)
        alice_notifs = self.alice_c.get("/api/notifications/").data
        self.assertEqual(alice_notifs[0]["type"], "live")
        self.assertIn("Night Talk", alice_notifs[0]["text"])
        self.assertIsNotNone(alice_notifs[0]["room"])

        self.assertEqual(self.alice_c.post("/api/notifications/read/").data["marked"], 1)
        self.assertEqual(self.alice_c.get("/api/notifications/unread-count/").data["unread"], 0)

    def test_notifications_are_private(self):
        self.alice_c.post(f"/api/auth/users/{self.host.id}/follow/")
        self.assertEqual(self.bob_c.get("/api/notifications/").data, [])
        self.assertEqual(Notification.objects.count(), 1)


class HandRaiseDecisionTests(RoomBase):
    def setUp(self):
        super().setUp()
        self.rid = self.create_room().data["id"]
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.alice_c.post(f"/api/rooms/{self.rid}/hand-raise/")

    def decide(self, decision, client=None, user=None):
        user = user or self.alice
        return (client or self.host_c).post(f"/api/rooms/{self.rid}/hand-raise/{user.id}/{decision}/")

    def test_requests_are_in_room_detail_oldest_first(self):
        self.bob_c.post(f"/api/rooms/{self.rid}/join/")
        self.bob_c.post(f"/api/rooms/{self.rid}/hand-raise/")
        hands = self.host_c.get(f"/api/rooms/{self.rid}/").data["hand_raises"]
        self.assertEqual([h["user"]["id"] for h in hands], [self.alice.id, self.bob.id])

    def test_approve_seats_user_muted_and_grants_publish(self):
        from unittest import mock

        Seat.objects.filter(room_id=self.rid, position=1).update(is_locked=True)
        with mock.patch("apps.rooms.views.voice_admin") as va:
            res = self.decide("approve")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["position"], 2)  # seat 0 = host, seat 1 locked
        seat = Seat.objects.get(room_id=self.rid, position=2)
        self.assertEqual(seat.user, self.alice)
        self.assertTrue(seat.is_muted)
        va.set_can_publish.assert_called_once()
        self.assertEqual(self.decide("approve").status_code, 404)  # request consumed

    def test_decline_and_permissions(self):
        self.assertEqual(self.decide("approve", client=self.bob_c).status_code, 403)
        self.assertEqual(self.decide("decline").data, {"declined": True})
        self.assertEqual(self.decide("maybe").status_code, 404)

    def test_no_free_seat(self):
        Seat.objects.filter(room_id=self.rid).exclude(position=0).update(is_locked=True)
        self.assertEqual(self.decide("approve").status_code, 409)


class ProfileLiveRoomTests(RoomBase):
    def test_profile_shows_room_being_hosted(self):
        self.assertIsNone(self.alice_c.get("/api/auth/users/hosty/").data["live_room"])
        rid = self.create_room(name="Late Talk").data["id"]
        self.assertEqual(self.alice_c.get("/api/auth/users/hosty/").data["live_room"], {"id": rid, "name": "Late Talk"})


class ReviewFixTests(RoomBase):
    """Regressions from the spec review."""

    def setUp(self):
        super().setUp()
        self.rid = self.create_room().data["id"]
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.alice_c.post(f"/api/rooms/{self.rid}/seats/1/take/")

    def seat(self, pos):
        return Seat.objects.get(room_id=self.rid, position=pos)

    def test_host_mute_survives_changing_seats_and_rejoining(self):
        self.host_c.post(f"/api/rooms/{self.rid}/seats/1/force-mute/")
        res = self.alice_c.post(f"/api/rooms/{self.rid}/seats/2/take/")
        self.assertEqual(res.data, {"is_muted": True, "muted_by_host": True})
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/2/mute/").status_code, 403)

        self.alice_c.post(f"/api/rooms/{self.rid}/leave/")
        self.alice_c.post(f"/api/rooms/{self.rid}/join/")
        self.alice_c.post(f"/api/rooms/{self.rid}/seats/3/take/")
        self.assertTrue(self.seat(3).muted_by_host)
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/3/mute/").status_code, 403)

        self.host_c.post(f"/api/rooms/{self.rid}/seats/3/force-mute/", {"muted": False}, format="json")
        self.assertEqual(self.alice_c.post(f"/api/rooms/{self.rid}/seats/3/mute/").data, {"is_muted": False})

    def test_taking_a_seat_requires_joining_first(self):
        self.assertEqual(self.bob_c.post(f"/api/rooms/{self.rid}/seats/4/take/").status_code, 403)
        self.assertIsNone(self.seat(4).user)

    def test_user_blocked_by_host_cannot_take_seat(self):
        self.bob_c.post(f"/api/rooms/{self.rid}/join/")
        Block.objects.create(blocker=self.host, blocked=self.bob)
        self.assertEqual(self.bob_c.post(f"/api/rooms/{self.rid}/seats/4/take/").status_code, 403)

    def test_moderator_cannot_mute_or_evict_another_moderator(self):
        self.bob_c.post(f"/api/rooms/{self.rid}/join/")
        for u in (self.alice, self.bob):
            RoomModerator.objects.create(room_id=self.rid, user=u)
        self.assertEqual(self.bob_c.post(f"/api/rooms/{self.rid}/seats/1/force-mute/").status_code, 403)
        self.assertEqual(self.bob_c.post(f"/api/rooms/{self.rid}/seats/1/lock/").status_code, 403)
        self.assertEqual(self.seat(1).user, self.alice)
        self.assertFalse(self.seat(1).is_locked)  # the failed lock rolled back

    def test_cleanup_closes_voice_session_of_ended_room(self):
        from datetime import timedelta
        from unittest import mock

        from django.core.management import call_command
        from django.utils import timezone

        from .models import Room, RoomParticipant

        RoomParticipant.objects.filter(room_id=self.rid).delete()
        Room.objects.filter(id=self.rid).update(created_at=timezone.now() - timedelta(minutes=30))
        with mock.patch("apps.rooms.management.commands.cleanup_stale_rooms.voice_admin") as va:
            call_command("cleanup_stale_rooms")
        va.close_room.assert_called_once()


class SocketRevocationTests(RoomBase):
    def test_password_change_revokes_socket_tokens(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        # The plain function: its database_sync_to_async wrapper closes "old"
        # connections, which kills TestCase's transaction on PostgreSQL.
        from config.jwt_auth_middleware import user_from_token

        token = str(RefreshToken.for_user(self.alice).access_token)
        self.assertEqual(user_from_token(token), self.alice)
        self.alice.set_password("An0ther-Strong-Pass!")
        self.alice.save()
        self.assertFalse(user_from_token(token).is_authenticated)
