from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def get_user_from_token(token):
    from django.contrib.auth import get_user_model

    try:
        user_id = AccessToken(token)["user_id"]
        user = get_user_model().objects.get(id=user_id)
    except (TokenError, KeyError, get_user_model().DoesNotExist, ValueError, TypeError):
        return AnonymousUser()
    return user if user.is_active else AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """Client connects with wss://.../ws/rooms/1/?token=<access_token>
    since browsers can't set custom headers on a WebSocket handshake.
    Access tokens are short-lived, but make sure the proxy/access logs do not
    record the query string for /ws/ paths."""

    async def __call__(self, scope, receive, send):
        query_params = parse_qs(scope["query_string"].decode())
        token = query_params.get("token", [None])[0]
        scope["user"] = await get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
