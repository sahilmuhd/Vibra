import uuid

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HandRaise, Message, Room, Seat
from .realtime import broadcast_to_room
from .serializers import (
    HandRaiseSerializer,
    MessageSerializer,
    RoomDetailSerializer,
    RoomListSerializer,
)


class RoomListCreateView(generics.ListCreateAPIView):
    queryset = Room.objects.filter(is_live=True).order_by("-created_at")
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return RoomListSerializer if self.request.method == "GET" else RoomListSerializer

    def perform_create(self, serializer):
        room = serializer.save(
            host=self.request.user,
            voice_room_name=f"vibra-{uuid.uuid4().hex[:12]}",
        )
        Seat.objects.bulk_create(
            [Seat(room=room, position=i) for i in range(room.seat_count)]
        )
        # Host auto-takes seat 0
        seat0 = room.seats.get(position=0)
        seat0.user = self.request.user
        seat0.is_muted = False
        seat0.save(update_fields=["user", "is_muted"])


class RoomDetailView(generics.RetrieveAPIView):
    queryset = Room.objects.all()
    serializer_class = RoomDetailSerializer
    permission_classes = [permissions.IsAuthenticated]


class TakeSeatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        seat = get_object_or_404(Seat, room=room, position=position)

        if seat.user_id is not None:
            return Response({"detail": "Seat taken."}, status=status.HTTP_409_CONFLICT)
        if seat.is_locked and room.host_id != request.user.id:
            return Response({"detail": "Seat locked."}, status=status.HTTP_403_FORBIDDEN)

        # Free any seat this user already holds in the room (one seat per user)
        Seat.objects.filter(room=room, user=request.user).update(user=None, is_muted=True)

        seat.user = request.user
        seat.save(update_fields=["user"])
        HandRaise.objects.filter(room=room, user=request.user).delete()

        broadcast_to_room(room.id, "seat.update", {
            "position": position, "user_id": request.user.id, "action": "taken",
        })
        return Response(status=status.HTTP_200_OK)


class LeaveSeatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        seat = get_object_or_404(Seat, room=room, position=position, user=request.user)
        seat.user = None
        seat.is_muted = True
        seat.save(update_fields=["user", "is_muted"])

        broadcast_to_room(room.id, "seat.update", {"position": position, "action": "left"})
        return Response(status=status.HTTP_200_OK)


class ToggleMuteView(APIView):
    """Self-mute only. A host force-muting someone else is a separate,
    permission-checked endpoint — don't conflate the two."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        seat = get_object_or_404(Seat, room_id=room_id, position=position, user=request.user)
        seat.is_muted = not seat.is_muted
        seat.save(update_fields=["is_muted"])
        broadcast_to_room(room_id, "seat.mute", {"position": position, "is_muted": seat.is_muted})
        return Response({"is_muted": seat.is_muted})


class RaiseHandView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        hand, _ = HandRaise.objects.get_or_create(room=room, user=request.user)
        broadcast_to_room(room.id, "hand.raised", HandRaiseSerializer(hand).data)
        return Response(status=status.HTTP_201_CREATED)


class MessageListCreateView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Message.objects.filter(room_id=self.kwargs["room_id"]).order_by("-created_at")[:50]

    def perform_create(self, serializer):
        message = serializer.save(room_id=self.kwargs["room_id"], user=self.request.user)
        broadcast_to_room(
            message.room_id, "message.new", MessageSerializer(message).data
        )
