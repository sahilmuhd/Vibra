import uuid

from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.profiles import ensure_profile
from apps.accounts.serializers import PublicUserSerializer

from .models import HandRaise, Message, Room, RoomParticipant, Seat
from .realtime import broadcast_to_room
from .serializers import (
    HandRaiseSerializer,
    MessageSerializer,
    RoomDetailSerializer,
    RoomListSerializer,
)


def room_queryset():
    """Rooms with host/profile/seat users preloaded and the live participant
    count annotated, so list + detail don't run N+1 queries."""
    return (
        Room.objects.select_related("host__profile")
        .prefetch_related("seats__user__profile")
        .annotate(online_total=Count("participants", distinct=True))
    )


class RoomListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RoomListSerializer

    def get_queryset(self):
        qs = room_queryset().filter(is_live=True).order_by("-created_at")
        category = (self.request.query_params.get("category") or "").strip().lower()
        if category:
            qs = qs.filter(category=category)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        # Atomic: previously a failure mid-way left a room with no/partial seats.
        ensure_profile(self.request.user)
        room = serializer.save(
            host=self.request.user,
            voice_room_name=f"vibra-{uuid.uuid4().hex[:12]}",
        )
        Seat.objects.bulk_create(
            [Seat(room=room, position=i) for i in range(room.seat_count)]
        )
        # Host auto-takes seat 0 (unmuted) and is the first participant.
        Seat.objects.filter(room=room, position=0).update(user=self.request.user, is_muted=False)
        RoomParticipant.objects.create(room=room, user=self.request.user)


class RoomDetailView(generics.RetrieveAPIView):
    queryset = room_queryset()
    serializer_class = RoomDetailSerializer
    permission_classes = [permissions.IsAuthenticated]


class JoinRoomView(APIView):
    """Registers the caller as being in the room and returns the full room
    snapshot (seats included). Idempotent."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if not room.is_live:
            return Response({"detail": "This room has ended."}, status=status.HTTP_410_GONE)
        ensure_profile(request.user)
        _, created = RoomParticipant.objects.get_or_create(room=room, user=request.user)
        snapshot = room_queryset().get(id=room.id)
        if created:
            broadcast_to_room(room.id, "presence.update", {
                "user": PublicUserSerializer(request.user).data,
                "action": "joined",
                "online_count": snapshot.online_total,
            })
        return Response(RoomDetailSerializer(snapshot).data)


class LeaveRoomView(APIView):
    """Leaves the room: frees any seat the caller holds, withdraws a pending
    hand-raise and removes them from the participant list. Idempotent, and
    allowed even if the room has already ended."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        freed = []
        with transaction.atomic():
            for seat in Seat.objects.select_for_update().filter(room=room, user=request.user):
                seat.user = None
                seat.is_muted = True
                seat.save(update_fields=["user", "is_muted"])
                freed.append(seat.position)
            HandRaise.objects.filter(room=room, user=request.user).delete()
            removed, _ = RoomParticipant.objects.filter(room=room, user=request.user).delete()
        # Broadcast only after the transaction has committed.
        for position in freed:
            broadcast_to_room(room.id, "seat.update", {"position": position, "action": "left"})
        if removed:
            broadcast_to_room(room.id, "presence.update", {
                "user_id": request.user.id,
                "action": "left",
                "online_count": RoomParticipant.objects.filter(room=room).count(),
            })
        return Response({"left": True, "released_seats": freed})


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

    def get_room(self):
        # 404 (not a 500 IntegrityError) for a room that does not exist.
        if not hasattr(self, "_room"):
            self._room = get_object_or_404(Room, id=self.kwargs["room_id"])
        return self._room

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["room"] = self.get_room()
        return context

    def get_queryset(self):
        # Newest first (the frontend reverses it). Contract unchanged.
        return (
            Message.objects.filter(room=self.get_room())
            .select_related("user__profile")
            .order_by("-created_at", "-id")[:50]
        )

    def perform_create(self, serializer):
        room = self.get_room()
        if not room.is_live:
            raise PermissionDenied("This room has ended.")
        if not RoomParticipant.objects.filter(room=room, user=self.request.user).exists():
            raise PermissionDenied("Join the room before sending messages.")
        message = serializer.save(room=room, user=self.request.user)
        broadcast_to_room(
            message.room_id, "message.new", MessageSerializer(message).data
        )
