from rest_framework import serializers

from .models import DirectMessage


class DirectMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DirectMessage
        fields = ["id", "sender_id", "text", "created_at", "read_at"]
        read_only_fields = ["id", "sender_id", "created_at", "read_at"]

    def validate_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        return value
