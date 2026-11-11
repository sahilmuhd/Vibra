import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Block
from apps.accounts.profiles import ensure_profile
from apps.accounts.serializers import PublicUserSerializer
from apps.notifications.services import notify_followers_live

from . import voice_admin
from .models import (
    HandRaise, Message, Report, Room, RoomBan, RoomModerator, RoomParticipant, Seat,
)
from .realtime import broadcast_to_room
from .serializers import (
    HandRaiseSerializer,
    MessageSerializer,
    RoomDetailSerializer,
    RoomListSerializer,
)
from .services import can_moderate, is_host, remove_user_from_room, user_in_room

MAX_LIVE_ROOMS_PER_HOST = 3
ROOM_LIST_LIMIT = 100
ENDED = {"detail": "This room has ended."}
BANNED = {"detail": "You have been removed from this room."}


def is_banned(room, user) -> bool:
    return RoomBan.objects.filter(room=room, user=user).exists()


def room_queryset():
    """Rooms with host/profile/seat users preloaded and the live participant
    count annotated, so list + detail don't run N+1 queries."""
    return (
        Room.objects.select_related("host__profile")
        .prefetch_related("seats__user__profile", "moderators", "hand_raises__user__profile")
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
        return qs[:ROOM_LIST_LIMIT]

    @transaction.atomic
    def perform_create(self, serializer):
        # Atomic: previously a failure mid-way left a room with no/partial seats.
        ensure_profile(self.request.user)
        live = Room.objects.filter(host=self.request.user, is_live=True).count()
        if live >= MAX_LIVE_ROOMS_PER_HOST:
            raise PermissionDenied(
                f"You can host at most {MAX_LIVE_ROOMS_PER_HOST} live rooms at a time."
            )
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
        notify_followers_live(self.request.user, room)


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
            return Response(ENDED, status=status.HTTP_410_GONE)
        if is_banned(room, request.user) or Block.objects.filter(
            blocker_id=room.host_id, blocked=request.user
        ).exists():
            return Response(BANNED, status=status.HTTP_403_FORBIDDEN)
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
        freed, removed = remove_user_from_room(room, request.user.id)
        # Broadcast only after the transaction has committed.
        for position in freed:
            broadcast_to_room(room.id, "seat.update", {"position": position, "action": "left"})
        if freed:
            voice_admin.set_can_publish(room, request.user.id, False)
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
            return Response(ENDED, status=status.HTTP_410_GONE)
        if is_banned(room, request.user):
            return Response(BANNED, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            seat = get_object_or_404(Seat.objects.select_for_update(), room=room, position=position)

            if seat.user_id is not None:
                return Response({"detail": "Seat taken."}, status=status.HTTP_409_CONFLICT)
            if seat.is_locked and room.host_id != request.user.id:
                return Response({"detail": "Seat locked."}, status=status.HTTP_403_FORBIDDEN)

            # Free any seat this user already holds in the room (one seat per user)
            Seat.objects.filter(room=room, user=request.user).update(
                user=None, is_muted=True, muted_by_host=False
            )

            seat.user = request.user
            # Taking a seat yourself means you're about to talk: the client turns the
            # mic on, so record it as live (approved hand-raises arrive muted instead).
            seat.is_muted = False
            seat.muted_by_host = False
            seat.save(update_fields=["user", "is_muted", "muted_by_host"])
            HandRaise.objects.filter(room=room, user=request.user).delete()

        broadcast_to_room(room.id, "seat.update", {
            "position": position, "user_id": request.user.id, "action": "taken",
        })
        # The voice token was minted before this user had a seat; let them publish now.
        voice_admin.set_can_publish(room, request.user.id, True)
        return Response(status=status.HTTP_200_OK)


class LeaveSeatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        with transaction.atomic():
            seat = get_object_or_404(
                Seat.objects.select_for_update(), room=room, position=position, user=request.user
            )
            seat.user = None
            seat.is_muted = True
            seat.muted_by_host = False
            seat.save(update_fields=["user", "is_muted", "muted_by_host"])

        broadcast_to_room(room.id, "seat.update", {"position": position, "action": "left"})
        voice_admin.set_can_publish(room, request.user.id, False)
        return Response(status=status.HTTP_200_OK)


class ToggleMuteView(APIView):
    """Self-mute only. A host force-muting someone else is a separate,
    permission-checked endpoint — don't conflate the two. A speaker the host
    has muted cannot unmute themselves until the host lifts the restriction."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        with transaction.atomic():
            seat = get_object_or_404(
                Seat.objects.select_for_update(), room_id=room_id, position=position, user=request.user
            )
            if seat.is_muted and seat.muted_by_host:
                raise PermissionDenied("The host has muted you.")
            seat.is_muted = not seat.is_muted
            seat.save(update_fields=["is_muted"])
        broadcast_to_room(room_id, "seat.mute", {"position": position, "is_muted": seat.is_muted})
        return Response({"is_muted": seat.is_muted})


class RaiseHandView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if not room.is_live:
            return Response(ENDED, status=status.HTTP_410_GONE)
        if not user_in_room(room, request.user):
            raise PermissionDenied("Join the room first.")

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
            Seat.objects.filter(room=room).update(user=None, is_muted=True, muted_by_host=False)
            HandRaise.objects.filter(room=room).delete()
            RoomParticipant.objects.filter(room=room).delete()

        broadcast_to_room(room.id, "room.ended", {"room_id": room.id})
        voice_admin.close_room(room)
        return Response({"ended": True, "room_id": room.id}, status=status.HTTP_200_OK)


class ForceMuteSeatView(APIView):
    """Host-only: force-mutes an occupied speaker seat. Send {"muted": false}
    to lift the restriction (the speaker stays muted until they unmute)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        if not can_moderate(room, request.user):
            raise PermissionDenied("Only the host or a moderator can mute speakers.")

        with transaction.atomic():
            seat = get_object_or_404(Seat.objects.select_for_update(), room=room, position=position)
            if seat.user_id is None:
                return Response({"detail": "Seat is unoccupied."}, status=status.HTTP_400_BAD_REQUEST)
            if seat.user_id == room.host_id and not is_host(room, request.user):
                raise PermissionDenied("Moderators cannot mute the host.")

            muted = request.data.get("muted", True) not in (False, "false", "False", 0, "0")
            seat.muted_by_host = muted
            if muted:
                seat.is_muted = True
            seat.save(update_fields=["is_muted", "muted_by_host"])

        broadcast_to_room(room.id, "seat.mute", {
            "position": position, "is_muted": seat.is_muted, "forced": muted,
        })
        # A host mute revokes publishing on the server; lifting it restores it.
        voice_admin.set_can_publish(room, seat.user_id, not muted)
        return Response({"position": position, "is_muted": seat.is_muted, "muted_by_host": muted})


class LockSeatView(APIView):
    """Host-only: toggles seat lock status. Locking an occupied seat removes any non-host occupant."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, position):
        room = get_object_or_404(Room, id=room_id)
        if not can_moderate(room, request.user):
            raise PermissionDenied("Only the host or a moderator can lock or unlock seats.")

        evicted_user_id = None
        with transaction.atomic():
            seat = get_object_or_404(Seat.objects.select_for_update(), room=room, position=position)
            seat.is_locked = not seat.is_locked
            if seat.is_locked and seat.user_id and seat.user_id != room.host_id:
                evicted_user_id = seat.user_id
                seat.user = None
                seat.is_muted = True
                seat.muted_by_host = False
            seat.save(update_fields=["is_locked", "user", "is_muted", "muted_by_host"])

        broadcast_to_room(room.id, "seat.lock", {
            "position": position,
            "is_locked": seat.is_locked,
            "evicted_user_id": evicted_user_id,
        })
        if evicted_user_id:
            broadcast_to_room(room.id, "seat.update", {"position": position, "action": "left"})
            voice_admin.set_can_publish(room, evicted_user_id, False)

        return Response({"position": position, "is_locked": seat.is_locked})


class KickParticipantView(APIView):
    """Host-only: removes a participant from the room (freeing their seat) and
    bans them from rejoining while the room is live."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if not can_moderate(room, request.user):
            raise PermissionDenied("Only the host or a moderator can kick participants.")

        target_user_id = request.data.get("user_id")
        if not target_user_id:
            return Response({"detail": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_user_id = int(target_user_id)
        except (ValueError, TypeError):
            return Response({"detail": "Invalid user_id."}, status=status.HTTP_400_BAD_REQUEST)

        if target_user_id == room.host_id:
            return Response({"detail": "Host cannot kick themselves."}, status=status.HTTP_400_BAD_REQUEST)
        if not get_user_model().objects.filter(id=target_user_id).exists():
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if target_user_id == request.user.id:
            return Response({"detail": "You cannot kick yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if not is_host(room, request.user) and RoomModerator.objects.filter(
            room=room, user_id=target_user_id
        ).exists():
            raise PermissionDenied("Only the host can remove a moderator.")

        with transaction.atomic():
            RoomBan.objects.get_or_create(room=room, user_id=target_user_id)
            freed_seats, _ = remove_user_from_room(room, target_user_id)

        for pos in freed_seats:
            broadcast_to_room(room.id, "seat.update", {"position": pos, "action": "left"})

        broadcast_to_room(room.id, "participant.kicked", {
            "user_id": target_user_id,
            "online_count": RoomParticipant.objects.filter(room=room).count(),
        })
        voice_admin.disconnect_user(room, target_user_id)

        return Response({"kicked": True, "user_id": target_user_id, "released_seats": freed_seats})


class MessageListCreateView(generics.ListCreateAPIView):
    throttle_scope = "chat"
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
        if not user_in_room(self.get_room(), self.request.user):
            raise PermissionDenied("Join the room to read its messages.")
        blocked = Block.objects.filter(blocker=self.request.user).values("blocked_id")
        return (
            Message.objects.filter(room=self.get_room())
            .exclude(user_id__in=blocked)
            .select_related("user__profile")
            .order_by("-created_at", "-id")[:50]
        )

    def perform_create(self, serializer):
        room = self.get_room()
        if not room.is_live:
            raise PermissionDenied("This room has ended.")
        if is_banned(room, self.request.user):
            raise PermissionDenied(BANNED["detail"])
        if not RoomParticipant.objects.filter(room=room, user=self.request.user).exists():
            raise PermissionDenied("Join the room before sending messages.")
        message = serializer.save(room=room, user=self.request.user)
        broadcast_to_room(
            message.room_id, "message.new", MessageSerializer(message).data
        )


class ModeratorView(APIView):
    """Host-only: appoint or remove a room moderator."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)
        if not is_host(room, request.user):
            raise PermissionDenied("Only the host can manage moderators.")
        try:
            target_id = int(request.data.get("user_id"))
        except (TypeError, ValueError):
            return Response({"detail": "Valid user_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if target_id == room.host_id:
            return Response({"detail": "The host already has full control."}, status=status.HTTP_400_BAD_REQUEST)
        if not RoomParticipant.objects.filter(room=room, user_id=target_id).exists():
            return Response({"detail": "That user is not in the room."}, status=status.HTTP_400_BAD_REQUEST)

        make_mod = request.data.get("is_moderator", True) not in (False, "false", "False", 0, "0")
        if make_mod:
            RoomModerator.objects.get_or_create(room=room, user_id=target_id)
        else:
            RoomModerator.objects.filter(room=room, user_id=target_id).delete()
        ids = list(RoomModerator.objects.filter(room=room).values_list("user_id", flat=True))
        broadcast_to_room(room.id, "moderators.update", {"moderator_ids": ids})
        return Response({"moderator_ids": ids})


class ReportView(APIView):
    """Any signed-in user can report a room and/or a user. Reports land in the
    Django admin for review."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "report"

    def post(self, request):
        reason = request.data.get("reason")
        if reason not in dict(Report.REASON_CHOICES):
            return Response({"detail": "Choose a valid reason."}, status=status.HTTP_400_BAD_REQUEST)
        room = reported = None
        if request.data.get("room_id") not in (None, ""):
            room = get_object_or_404(Room, id=request.data["room_id"])
        if request.data.get("user_id") not in (None, ""):
            reported = get_object_or_404(get_user_model(), id=request.data["user_id"])
            if reported.id == request.user.id:
                return Response({"detail": "You cannot report yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if room is None and reported is None:
            return Response({"detail": "Say what you are reporting."}, status=status.HTTP_400_BAD_REQUEST)
        report = Report.objects.create(
            reporter=request.user, room=room, reported_user=reported, reason=reason,
            details=str(request.data.get("details", ""))[:500],
        )
        return Response({"id": report.id}, status=status.HTTP_201_CREATED)


class HandRaiseDecisionView(APIView):
    """Host/moderator answers a raised hand.

    approve: seat the user in the first free, unlocked seat (they arrive muted
             and unmute themselves) and grant them publish rights in LiveKit.
    decline: drop the request.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id, user_id, decision):
        room = get_object_or_404(Room, id=room_id)
        if not room.is_live:
            return Response(ENDED, status=status.HTTP_410_GONE)
        if not can_moderate(room, request.user):
            raise PermissionDenied("Only the host or a moderator can answer requests.")
        if decision not in ("approve", "decline"):
            return Response({"detail": "Unknown decision."}, status=status.HTTP_404_NOT_FOUND)

        if decision == "decline":
            deleted, _ = HandRaise.objects.filter(room=room, user_id=user_id).delete()
            if deleted:
                broadcast_to_room(room.id, "hand.lowered", {"user_id": user_id, "declined": True})
            return Response({"declined": bool(deleted)})

        with transaction.atomic():
            hand = HandRaise.objects.select_for_update().filter(room=room, user_id=user_id).first()
            if hand is None:
                return Response({"detail": "That request is no longer open."}, status=status.HTTP_404_NOT_FOUND)
            if Seat.objects.filter(room=room, user_id=user_id).exists():
                hand.delete()
                return Response({"detail": "Already on mic."}, status=status.HTTP_409_CONFLICT)
            seat = (
                Seat.objects.select_for_update()
                .filter(room=room, user__isnull=True, is_locked=False)
                .order_by("position")
                .first()
            )
            if seat is None:
                return Response({"detail": "No free seats."}, status=status.HTTP_409_CONFLICT)
            seat.user_id = user_id
            seat.is_muted = True
            seat.muted_by_host = False
            seat.save(update_fields=["user", "is_muted", "muted_by_host"])
            hand.delete()

        broadcast_to_room(room.id, "hand.lowered", {"user_id": user_id, "approved": True})
        broadcast_to_room(room.id, "seat.update", {
            "position": seat.position, "user_id": user_id, "action": "taken", "invited": True,
        })
        voice_admin.set_can_publish(room, user_id, True)
        return Response({"approved": True, "position": seat.position})
