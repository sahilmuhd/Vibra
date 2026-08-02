from django.conf import settings
from django.shortcuts import get_object_or_404
from livekit import api
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Room


class VoiceTokenView(APIView):
    """Client calls this right after taking a seat, then hands the token to
    the LiveKit JS SDK to actually publish/subscribe audio. Django never
    touches the audio itself — it only decides who's allowed into which
    LiveKit room and for how long."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        seat = room.seats.filter(user=request.user).first()

        token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        token = token.with_identity(str(request.user.id)).with_name(
            request.user.profile.username
        )
        # Listeners (no seat) can subscribe but not publish audio; seated
        # users can publish. Mute state is still enforced client-side by
        # the LiveKit SDK reading `seat.is_muted` from the REST/WS state.
        can_publish = seat is not None
        token = token.with_grants(
            api.VideoGrants(
                room_join=True,
                room=room.voice_room_name,
                can_publish=can_publish,
                can_subscribe=True,
            )
        )
        return Response({"token": token.to_jwt(), "url": settings.LIVEKIT_URL, "room": room.voice_room_name})
