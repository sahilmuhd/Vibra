from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer

from .levels import level_info, room_level
from .models import Gift, GiftEvent, HandRaise, Message, Room, Seat


class RoomListSerializer(serializers.ModelSerializer):
    """Matches roomCardHTML() in the current frontend — name, category,
    desc, live status, online count, host."""
    host = PublicUserSerializer(read_only=True)
    online_count = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ["id", "name", "category", "description", "host", "is_live", "online_count", "thumbnail_seed",
                  "gift_total", "theme", "has_password", "level", "seat_count"]
        # Clients must not decide liveness or the thumbnail seed.
        read_only_fields = ["id", "is_live", "thumbnail_seed", "theme", "seat_count"]
        extra_kwargs = {"name": {"min_length": 2}}

    # Coins gifted in the room so far (the trophy score); annotated by room_queryset().
    gift_total = serializers.SerializerMethodField()

    has_password = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    def get_gift_total(self, obj):
        return getattr(obj, "gift_total", 0) or 0

    def get_has_password(self, obj):
        return bool(obj.password)

    def get_level(self, obj):
        return room_level(self.get_gift_total(obj))

    def get_online_count(self, obj):
        """Everyone currently in the room (listeners + speakers). Uses the
        queryset annotation when the view provides it to avoid N+1 queries."""
        annotated = getattr(obj, "online_total", None)
        return annotated if annotated is not None else obj.participants.count()


class SeatSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)

    class Meta:
        model = Seat
        fields = ["position", "user", "is_muted", "muted_by_host", "is_locked"]


class RoomDetailSerializer(RoomListSerializer):
    seats = SeatSerializer(many=True, read_only=True)
    moderator_ids = serializers.SerializerMethodField()
    hand_raises = serializers.SerializerMethodField()

    level_info = serializers.SerializerMethodField()

    class Meta(RoomListSerializer.Meta):
        fields = RoomListSerializer.Meta.fields + [
            "seats", "voice_room_name", "moderator_ids", "hand_raises",
            "announcement", "welcome_message", "slow_mode", "level_info",
        ]

    def get_level_info(self, obj):
        return level_info(self.get_gift_total(obj))

    def get_hand_raises(self, obj):
        # Oldest first: the host answers requests in the order they came in.
        return HandRaiseSerializer(obj.hand_raises.all(), many=True).data

    def get_moderator_ids(self, obj):
        return [m.user_id for m in obj.moderators.all()]


class MessageSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)
    text = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=False)
    voice = serializers.SerializerMethodField()

    def get_voice(self, obj):
        from apps.social.services import voice_payload
        return voice_payload(obj.voice)

    def validate(self, attrs):
        if not attrs.get("text") and not self.context.get("has_voice"):
            raise serializers.ValidationError({"text": "Message cannot be empty."})
        return attrs

    class Meta:
        model = Message
        fields = ["id", "room", "user", "text", "reply_to", "is_system", "voice", "created_at"]
        # `room` was previously writable and *required* in the body, so the
        # frontend's {text, reply_to} payload was rejected with a 400. The room
        # always comes from the URL.
        read_only_fields = ["id", "room", "user", "is_system", "created_at"]

    def validate_reply_to(self, value):
        room = self.context.get("room")
        if value is not None and room is not None and value.room_id != room.id:
            raise serializers.ValidationError("Cannot reply to a message from another room.")
        return value

    def validate_text(self, value):
        return value.strip()


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
