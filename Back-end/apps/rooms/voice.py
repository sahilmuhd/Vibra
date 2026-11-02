from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from livekit import api
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.profiles import ensure_profile

from .models import Room, RoomBan
from .services import user_in_room

TOKEN_TTL = timedelta(hours=1)


class VoiceTokenView(APIView):
    """Client calls this right after taking a seat, then hands the token to
    the LiveKit JS SDK to actually publish/subscribe audio. Django never
    touches the audio itself — it only decides who's allowed into which
    LiveKit room and for how long."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if not room.is_live:
            return Response({"detail": "This room has ended."}, status=status.HTTP_410_GONE)
        if RoomBan.objects.filter(room=room, user=request.user).exists():
            raise PermissionDenied("You have been removed from this room.")
        if not user_in_room(room, request.user):
            raise PermissionDenied("Join the room first.")

        seat = room.seats.filter(user=request.user).first()

        token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        token = token.with_identity(str(request.user.id)).with_name(
            ensure_profile(request.user).username
        ).with_ttl(TOKEN_TTL)
        # Only seated users can publish audio, and never while the host has
        # them muted. Self-mute is still applied client-side from `is_muted`.
        can_publish = seat is not None and not seat.muted_by_host
        token = token.with_grants(
            api.VideoGrants(
                room_join=True,
                room=room.voice_room_name,
                can_publish=can_publish,
                can_subscribe=True,
            )
        )
        return Response({"token": token.to_jwt(), "url": settings.LIVEKIT_URL, "room": room.voice_room_name})
