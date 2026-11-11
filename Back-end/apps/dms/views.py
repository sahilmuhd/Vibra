from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Block
from apps.accounts.serializers import PublicUserSerializer
from apps.rooms.realtime import broadcast_to_user

from .models import DirectMessage
from .serializers import DirectMessageSerializer
from .services import conversations_for, get_conversation

User = get_user_model()


class ConversationListView(APIView):
    """The caller's threads, newest activity first, with last message and unread count."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        me = request.user.id
        convos = (
            conversations_for(me)
            .select_related("user_a__profile", "user_b__profile")
            .annotate(unread=Count(
                "messages", filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender_id=me),
            ))[:50]
        )
        rows = []
        for c in convos:
            last = c.messages.order_by("-created_at", "-id").first()
            if last is None:
                continue
            rows.append({
                "user": PublicUserSerializer(c.other(me)).data,
                "last_message": DirectMessageSerializer(last).data,
                "unread": c.unread,
            })
        return Response(rows)


class UnreadDMCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        me = request.user.id
        count = DirectMessage.objects.filter(
            conversation__in=conversations_for(me), read_at__isnull=True,
        ).exclude(sender_id=me).count()
        return Response({"unread": count})


class ThreadView(APIView):
    """GET: last 100 messages with `user_id` (marks theirs as read).
    POST {text}: send a message to `user_id`."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "chat"

    def get(self, request, user_id):
        other = get_object_or_404(User.objects.select_related("profile"), id=user_id)
        convo = get_conversation(request.user.id, other.id)
        messages = []
        if convo:
            convo.messages.filter(sender_id=other.id, read_at__isnull=True).update(read_at=timezone.now())
            messages = list(convo.messages.order_by("-created_at", "-id")[:100])[::-1]
        return Response({
            "user": PublicUserSerializer(other).data,
            "blocked": Block.between(request.user.id, other.id),
            "messages": DirectMessageSerializer(messages, many=True).data,
        })

    def post(self, request, user_id):
        other = get_object_or_404(User, id=user_id)
        if other.id == request.user.id:
            return Response({"detail": "You cannot message yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if Block.between(request.user.id, other.id):
            raise PermissionDenied("You can't message this person.")
        serializer = DirectMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        convo = get_conversation(request.user.id, other.id, create=True)
        message = DirectMessage.objects.create(
            conversation=convo, sender=request.user, text=serializer.validated_data["text"],
        )
        convo.save(update_fields=["updated_at"])
        data = DirectMessageSerializer(message).data
        broadcast_to_user(other.id, "dm.new", {
            "from": PublicUserSerializer(request.user).data, "message": data,
        })
        return Response(data, status=status.HTTP_201_CREATED)
