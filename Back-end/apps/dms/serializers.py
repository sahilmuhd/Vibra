from rest_framework import serializers

from .models import DirectMessage


class DirectMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(read_only=True)
    text = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    voice = serializers.SerializerMethodField()

    class Meta:
        model = DirectMessage
        fields = ["id", "sender_id", "text", "voice", "created_at", "read_at"]
        read_only_fields = ["id", "sender_id", "created_at", "read_at"]

    def get_voice(self, obj):
        from apps.social.services import voice_payload
        return voice_payload(obj.voice)

    def validate_text(self, value):
        return value.strip()

    def validate(self, attrs):
        if not attrs.get("text") and not self.context.get("has_voice"):
            raise serializers.ValidationError({"text": "Message cannot be empty."})
        return attrs
