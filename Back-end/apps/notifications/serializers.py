from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor = PublicUserSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "type", "text", "actor", "room", "is_read", "created_at"]
