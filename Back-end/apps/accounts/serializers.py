from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Profile

User = get_user_model()


class PublicUserSerializer(serializers.ModelSerializer):
    """Safe-to-broadcast shape of a user — this is what other clients see,
    e.g. embedded in a Message, Seat, or GiftEvent payload."""
    username = serializers.CharField(source="profile.username")
    avatar_url = serializers.URLField(source="profile.avatar_url")
    level = serializers.IntegerField(source="profile.level")

    class Meta:
        model = User
        fields = ["id", "username", "avatar_url", "level"]


class ProfileSerializer(serializers.ModelSerializer):
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "username", "avatar_url", "bio", "country", "level",
            "followers_count", "following_count", "created_at",
        ]
        read_only_fields = ["level", "created_at"]

    def get_followers_count(self, obj):
        return obj.user.follower_set.count()

    def get_following_count(self, obj):
        return obj.user.following_set.count()


class SignupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    username = serializers.CharField(max_length=30)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    dob = serializers.DateField()

    def validate_username(self, value):
        value = value.lower().strip()
        if Profile.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already taken.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["name"],
        )
        Profile.objects.create(
            user=user,
            username=validated_data["username"],
            avatar_url=f"https://api.dicebear.com/7.x/notionists/svg?seed={validated_data['username']}",
        )
        return user
