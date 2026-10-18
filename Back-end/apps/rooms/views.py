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
        qs = room_queryset().filter(is_live=True).order_by("-created_at", "-id")
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
        if not room.is_live:
            return Response({"detail": "This room has ended."}, status=status.HTTP_410_GONE)

        with transaction.atomic():
            seat = get_object_or_404(Seat.objects.select_for_update(), room=room, position=position)

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
        if not room.is_live:
            return Response({"detail": "This room has ended."}, status=status.HTTP_410_GONE)

        hand = HandRaise.objects.filter(room=room, user=request.user).first()
        if hand:
            hand.delete()
            broadcast_to_room(room.id, "hand.lowered", {"user_id": request.user.id})
            return Response({"raised": False}, status=status.HTTP_200_OK)

        hand = HandRaise.objects.create(room=room, user=request.user)
        broadcast_to_room(room.id, "hand.raised", HandRaiseSerializer(hand).data)
        return Response({"raised": True, **HandRaiseSerializer(hand).data}, status=status.HTTP_201_CREATED)

    def delete(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        deleted, _ = HandRaise.objects.filter(room=room, user=request.user).delete()
        if deleted:
            broadcast_to_room(room.id, "hand.lowered", {"user_id": request.user.id})
        return Response({"raised": False}, status=status.HTTP_200_OK)


class EndRoomView(APIView):
    """Host-only: marks room as ended, frees seats, hand raises, and participants."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if room.host_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied("Only the host can end this room.")

        if not room.is_live:
            return Response({"detail": "Room already ended."}, status=status.HTTP_200_OK)

        with transaction.atomic():
            room.is_live = False
            room.save(update_fields=["is_live"])
            Seat.objects.filter(room=room).update(user=None, is_muted=True)
            HandRaise.objects.filter(room=room).delete()
            RoomParticipant.objects.filter(room=room).delete()

        broadcast_to_room(room.id, "room.ended", {"room_id": room.id})
        return Response({"ended": True, "room_id": room.id}, status=status.HTTP_200_OK)


class ForceMuteSeatView(APIView):
    """Host-only: force-mutes an occupied speaker seat."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        if room.host_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied("Only the host can mute other speakers.")

        seat = get_object_or_404(Seat, room=room, position=position)
        if seat.user_id is None:
            return Response({"detail": "Seat is unoccupied."}, status=status.HTTP_400_BAD_REQUEST)

        seat.is_muted = True
        seat.save(update_fields=["is_muted"])
        broadcast_to_room(room.id, "seat.mute", {"position": position, "is_muted": True, "forced": True})
        return Response({"position": position, "is_muted": True})


class LockSeatView(APIView):
    """Host-only: toggles seat lock status. Locking an occupied seat removes any non-host occupant."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        if room.host_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied("Only the host can lock or unlock seats.")

        evicted_user_id = None
        with transaction.atomic():
            seat = get_object_or_404(Seat.objects.select_for_update(), room=room, position=position)
            seat.is_locked = not seat.is_locked
            if seat.is_locked and seat.user_id and seat.user_id != room.host_id:
                evicted_user_id = seat.user_id
                seat.user = None
                seat.is_muted = True
            seat.save(update_fields=["is_locked", "user", "is_muted"])

        broadcast_to_room(room.id, "seat.lock", {
            "position": position,
            "is_locked": seat.is_locked,
            "evicted_user_id": evicted_user_id,
        })
        if evicted_user_id:
            broadcast_to_room(room.id, "seat.update", {"position": position, "action": "left"})

        return Response({"position": position, "is_locked": seat.is_locked})


class KickParticipantView(APIView):
    """Host-only: removes a participant from the room, freeing their seat if speaking."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if room.host_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied("Only the host can kick participants.")

        target_user_id = request.data.get("user_id")
        if not target_user_id:
            return Response({"detail": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_user_id = int(target_user_id)
        except (ValueError, TypeError):
            return Response({"detail": "Invalid user_id."}, status=status.HTTP_400_BAD_REQUEST)

        if target_user_id == room.host_id:
            return Response({"detail": "Host cannot kick themselves."}, status=status.HTTP_400_BAD_REQUEST)

        freed_seats = []
        with transaction.atomic():
            for seat in Seat.objects.select_for_update().filter(room=room, user_id=target_user_id):
                seat.user = None
                seat.is_muted = True
                seat.save(update_fields=["user", "is_muted"])
                freed_seats.append(seat.position)

            HandRaise.objects.filter(room=room, user_id=target_user_id).delete()
            removed, _ = RoomParticipant.objects.filter(room=room, user_id=target_user_id).delete()

        for pos in freed_seats:
            broadcast_to_room(room.id, "seat.update", {"position": pos, "action": "left"})

        broadcast_to_room(room.id, "participant.kicked", {
            "user_id": target_user_id,
            "online_count": RoomParticipant.objects.filter(room=room).count(),
        })

        return Response({"kicked": True, "user_id": target_user_id, "released_seats": freed_seats})


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
