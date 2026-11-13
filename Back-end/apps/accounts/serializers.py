import re
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .levels import is_admin, level_for, level_progress, vip_for, vip_progress
from .models import Profile

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
MIN_SIGNUP_AGE = 13

User = get_user_model()


class PublicUserSerializer(serializers.ModelSerializer):
    """Safe-to-broadcast shape of a user — this is what other clients see,
    e.g. embedded in a Message, Seat, or GiftEvent payload."""
    username = serializers.CharField(source="profile.username")
    avatar_url = serializers.URLField(source="profile.avatar_url")
    level = serializers.IntegerField(source="profile.level")
    # Status shown next to names everywhere (all read from the already-loaded profile).
    wealth_level = serializers.SerializerMethodField()
    charm_level = serializers.SerializerMethodField()
    vip = serializers.SerializerMethodField()
    frame = serializers.SerializerMethodField()
    mount = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "avatar_url", "level", "wealth_level", "charm_level", "vip", "frame", "mount",
                  "is_admin"]

    def get_is_admin(self, user):
        return is_admin(user)

    def get_wealth_level(self, user):
        return level_for(user.profile.wealth_xp)

    def get_charm_level(self, user):
        return level_for(user.profile.charm_xp)

    def get_vip(self, user):
        return 5 if is_admin(user) else vip_for(user.profile.wealth_xp)

    def get_frame(self, user):
        return user.profile.active_frame()

    def get_mount(self, user):
        return user.profile.active_mount()


class ProfileSerializer(serializers.ModelSerializer):
    # The frontend needs the numeric user id to recognise "me" (host checks,
    # seat ownership) without comparing usernames.
    id = serializers.IntegerField(source="user_id", read_only=True)
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    # Relationship of the *viewer* to this profile (false when there is no request).
    is_following = serializers.SerializerMethodField()
    is_blocked = serializers.SerializerMethodField()
    live_room = serializers.SerializerMethodField()
    wealth = serializers.SerializerMethodField()
    charm = serializers.SerializerMethodField()
    vip = serializers.SerializerMethodField()
    frame = serializers.SerializerMethodField()
    mount = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "id", "username", "avatar_url", "bio", "country", "level",
            "followers_count", "following_count", "is_following", "is_blocked",
            "live_room", "created_at", "wealth", "charm", "vip", "frame", "mount", "is_admin",
        ]
        # `username` is read-only here: it is mirrored on auth.User (used for
        # login), and PATCHing only Profile.username silently desynced the two.
        # Proper rename support is planned for Phase 3 (profile editing).
        read_only_fields = ["id", "username", "level", "created_at"]

    def get_followers_count(self, obj):
        return obj.user.follower_set.count()

    def get_following_count(self, obj):
        return obj.user.following_set.count()

    def _viewer(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return user if user is not None and user.is_authenticated else None

    def get_is_following(self, obj):
        viewer = self._viewer()
        return bool(viewer) and obj.user.follower_set.filter(follower=viewer).exists()

    def get_wealth(self, obj):
        return level_progress(obj.wealth_xp)

    def get_charm(self, obj):
        return level_progress(obj.charm_xp)

    def get_vip(self, obj):
        return vip_progress(obj.wealth_xp, admin=is_admin(obj.user))

    def get_is_admin(self, obj):
        return is_admin(obj.user)

    def get_frame(self, obj):
        return obj.active_frame()

    def get_mount(self, obj):
        return obj.active_mount()

    def get_live_room(self, obj):
        """The room this user is hosting right now, if any (for "Live now" on profiles)."""
        room = obj.user.hosted_rooms.filter(is_live=True).order_by("-created_at").first()
        return {"id": room.id, "name": room.name} if room else None

    def get_is_blocked(self, obj):
        viewer = self._viewer()
        return bool(viewer) and viewer.blocks_made.filter(blocked_id=obj.user_id).exists()


class SignupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    username = serializers.CharField(max_length=30)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    dob = serializers.DateField()

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_username(self, value):
        value = value.lower().strip()
        if not USERNAME_RE.match(value):
            raise serializers.ValidationError(
                "Username must be 3-30 characters: lowercase letters, numbers or underscore."
            )
        if (
            Profile.objects.filter(username=value).exists()
            or User.objects.filter(username__iexact=value).exists()
        ):
            raise serializers.ValidationError("Username already taken.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def validate_dob(self, value):
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if value > today:
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        if age < MIN_SIGNUP_AGE:
            raise serializers.ValidationError(f"You must be at least {MIN_SIGNUP_AGE} to join Vibra.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        # Atomic: a User without a Profile would 500 on every /me/ call.
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


class VibraTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login with username OR email, case-insensitively.

    Signup lower-cases usernames, but SimpleJWT's default login is
    case-sensitive, so "Sahil" could never log in as "sahil"."""

    def validate(self, attrs):
        ident = (attrs.get(self.username_field) or "").strip()
        if "@" in ident:
            match = User.objects.filter(email__iexact=ident).first()
            if match:
                ident = match.get_username()
        else:
            ident = ident.lower()
        attrs[self.username_field] = ident
        return super().validate(attrs)
