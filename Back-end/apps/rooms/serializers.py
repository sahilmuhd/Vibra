from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer

from .models import Gift, GiftEvent, HandRaise, Message, Room, Seat


class RoomListSerializer(serializers.ModelSerializer):
    """Matches roomCardHTML() in the current frontend — name, category,
    desc, live status, online count, host."""
    host = PublicUserSerializer(read_only=True)
    online_count = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ["id", "name", "category", "description", "host", "is_live", "online_count", "thumbnail_seed"]

    def get_online_count(self, obj):
        return obj.seats.exclude(user=None).count()


class SeatSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)

    class Meta:
        model = Seat
        fields = ["position", "user", "is_muted", "is_locked"]


class RoomDetailSerializer(RoomListSerializer):
    seats = SeatSerializer(many=True, read_only=True)

    class Meta(RoomListSerializer.Meta):
        fields = RoomListSerializer.Meta.fields + ["seats", "voice_room_name"]


class MessageSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "room", "user", "text", "reply_to", "is_system", "created_at"]
        read_only_fields = ["user", "is_system", "created_at"]

    def validate_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        return value


class GiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gift
        fields = ["id", "name", "emoji", "cost", "animation_key"]


class SendGiftSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()
    recipient_id = serializers.IntegerField()
    gift_id = serializers.IntegerField()
    combo = serializers.IntegerField(min_value=1, max_value=99, default=1)


class HandRaiseSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)

    class Meta:
        model = HandRaise
        fields = ["id", "user", "created_at"]
