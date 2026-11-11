from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    """Newest 50 notifications for the caller."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.notifications.select_related("actor__profile")[:50]


class UnreadCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"unread": request.user.notifications.filter(is_read=False).count()})


class MarkReadView(APIView):
    """Marks all (or the given `ids`) of the caller's notifications as read."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        qs = request.user.notifications.filter(is_read=False)
        ids = request.data.get("ids")
        if isinstance(ids, list):
            qs = qs.filter(id__in=[i for i in ids if isinstance(i, int)])
        updated = qs.update(is_read=True)
        return Response({"marked": updated})
