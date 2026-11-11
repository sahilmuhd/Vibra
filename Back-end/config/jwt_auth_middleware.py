from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.utils import get_md5_hash_password


@database_sync_to_async
def get_user_from_token(token):
    from django.contrib.auth import get_user_model

    try:
        access = AccessToken(token)
        user = get_user_model().objects.get(id=access["user_id"])
    except (TokenError, KeyError, get_user_model().DoesNotExist, ValueError, TypeError):
        return AnonymousUser()
    if not user.is_active:
        return AnonymousUser()
    # Same revocation rule as the REST API: a password change kills old tokens.
    if api_settings.CHECK_REVOKE_TOKEN and access.get(api_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(user.password):
        return AnonymousUser()
    return user


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
