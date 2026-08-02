from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def get_user_from_token(token):
    from django.contrib.auth import get_user_model

    try:
        access_token = AccessToken(token)
        user_id = access_token["user_id"]
        return get_user_model().objects.get(id=user_id)
    except (InvalidToken, KeyError, Exception):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """Client connects with wss://.../ws/rooms/1/?token=<access_token>
    since browsers can't set custom headers on a WebSocket handshake."""

    async def __call__(self, scope, receive, send):
        query_params = parse_qs(scope["query_string"].decode())
        token = query_params.get("token", [None])[0]
        scope["user"] = await get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
