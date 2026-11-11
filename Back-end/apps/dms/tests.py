from unittest import mock

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Block
from apps.rooms.tests import RoomBase, make_user
from config.jwt_auth_middleware import JWTAuthMiddleware
from config.routing import websocket_urlpatterns

from .models import Conversation, DirectMessage


class DirectMessageTests(RoomBase):
    def send(self, client, to, text):
        return client.post(f"/api/dms/{to.id}/", {"text": text}, format="json")

    def test_send_list_read_flow(self):
        with mock.patch("apps.dms.views.broadcast_to_user") as push:
            res = self.send(self.alice_c, self.bob, "hey bob")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(push.call_args.args[:2], (self.bob.id, "dm.new"))
        self.send(self.bob_c, self.alice, "hi alice")
        self.send(self.alice_c, self.bob, "how are you")
        self.assertEqual(Conversation.objects.count(), 1)

        self.assertEqual(self.bob_c.get("/api/dms/unread-count/").data["unread"], 2)
        convos = self.bob_c.get("/api/dms/").data
        self.assertEqual(convos[0]["user"]["id"], self.alice.id)
        self.assertEqual(convos[0]["last_message"]["text"], "how are you")
        self.assertEqual(convos[0]["unread"], 2)

        thread = self.bob_c.get(f"/api/dms/{self.alice.id}/").data
        self.assertEqual([m["text"] for m in thread["messages"]], ["hey bob", "hi alice", "how are you"])
        self.assertEqual(self.bob_c.get("/api/dms/unread-count/").data["unread"], 0)

    def test_validation_and_blocking(self):
        self.assertEqual(self.send(self.alice_c, self.alice, "me").status_code, 400)
        self.assertEqual(self.send(self.alice_c, self.bob, "   ").status_code, 400)
        Block.objects.create(blocker=self.bob, blocked=self.alice)
        self.assertEqual(self.send(self.alice_c, self.bob, "let me in").status_code, 403)
        self.assertEqual(self.send(self.bob_c, self.alice, "bye").status_code, 403)
        self.assertTrue(self.alice_c.get(f"/api/dms/{self.bob.id}/").data["blocked"])
        self.assertEqual(DirectMessage.objects.count(), 0)

    def test_threads_are_private(self):
        self.send(self.alice_c, self.bob, "secret")
        self.assertEqual(self.host_c.get("/api/dms/").data, [])
        self.assertEqual(self.host_c.get(f"/api/dms/{self.alice.id}/").data["messages"], [])


class UserSocketTests(TransactionTestCase):
    async def test_personal_socket_receives_dms_and_rejects_anonymous(self):
        from channels.db import database_sync_to_async
        from rest_framework.test import APIClient

        app = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        bob = await database_sync_to_async(make_user)("bobby")
        alice = await database_sync_to_async(make_user)("alice")

        anon = WebsocketCommunicator(app, "/ws/me/")
        self.assertFalse((await anon.connect())[0])

        sock = WebsocketCommunicator(app, f"/ws/me/?token={AccessToken.for_user(bob)}")
        self.assertTrue((await sock.connect())[0])

        def send():
            client = APIClient()
            client.force_authenticate(alice)
            return client.post(f"/api/dms/{bob.id}/", {"text": "ping"}, format="json").status_code

        self.assertEqual(await database_sync_to_async(send)(), 201)
        event = await sock.receive_json_from(timeout=2)
        self.assertEqual((event["event"], event["message"]["text"], event["from"]["id"]), ("dm_new", "ping", alice.id))
        await sock.disconnect()
