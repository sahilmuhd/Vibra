import logging
import secrets
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.cache import cache
from django.db import transaction
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.notifications.services import notify
from apps.notifications.models import Notification

from .models import Block, Follow, Profile
from .profiles import ensure_profile
from .serializers import (
    ProfileSerializer, PublicUserSerializer, SignupSerializer, VibraTokenObtainPairSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class LoginView(TokenObtainPairView):
    throttle_scope = "auth"
    serializer_class = VibraTokenObtainPairSerializer


class SignupView(APIView):
    throttle_scope = "auth"
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"user": ProfileSerializer(user.profile).data, **tokens_for(user)},
            status=status.HTTP_201_CREATED,
        )


class GuestLoginView(APIView):
    """Matches the prototype's 'Continue as Guest' button — creates a
    throwaway account so the product can still be tried without signup."""
    throttle_scope = "auth"
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        suffix = uuid.uuid4().hex[:8]
        username = f"guest{suffix}"
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=uuid.uuid4().hex)
            Profile.objects.create(
                user=user,
                username=username,
                avatar_url=f"https://api.dicebear.com/7.x/notionists/svg?seed={username}",
                is_guest=True,
            )
        return Response(
            {"user": ProfileSerializer(user.profile).data, **tokens_for(user)},
            status=status.HTTP_201_CREATED,
        )


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return ensure_profile(self.request.user)


class PublicProfileView(generics.RetrieveAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "username"
    queryset = Profile.objects.all()


class PasswordResetRequestView(APIView):
    """Step 1: User submits their email. We generate a secure token,
    cache it for 1 hour, and email a reset link."""
    throttle_scope = "auth"
    permission_classes = [permissions.AllowAny]
    CACHE_TTL = 3600  # 1 hour

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Always return 200 so we don't leak whether an email exists
        user_qs = User.objects.filter(email__iexact=email)
        if user_qs.exists():
            user = user_qs.first()
            token = secrets.token_urlsafe(48)
            cache_key = f"pw_reset_{token}"
            cache.set(cache_key, user.pk, self.CACHE_TTL)

            frontend_url = getattr(settings, "FRONTEND_URL", "https://vibra.sahilmuhd.com")
            reset_link = f"{frontend_url}/?reset_token={token}"

            try:
                send_mail(
                    subject="Reset your Vibra password",
                    message=(
                        f"Hi {user.username},\n\n"
                        f"Someone requested a password reset for your Vibra account.\n"
                        f"Click the link below to set a new password (expires in 1 hour):\n\n"
                        f"{reset_link}\n\n"
                        f"If you didn't request this, just ignore this email.\n\n"
                        f"— The Vibra Team"
                    ),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@vibra.sahilmuhd.com"),
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception:  # noqa: BLE001 - never reveal delivery failure to the caller
                logger.exception("Password reset email failed for user %s", user.pk)

        return Response({"detail": "If that email is registered, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    """Step 2: User clicks the link, submits token + new password."""
    throttle_scope = "auth"
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        new_password = request.data.get("new_password") or ""

        if not token or not new_password:
            return Response(
                {"detail": "Token and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(new_password) < 8:
            return Response(
                {"detail": "Password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"pw_reset_{token}"
        user_pk = cache.get(cache_key)
        if not user_pk:
            return Response(
                {"detail": "Reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        cache.delete(cache_key)  # one-time use

        return Response({"detail": "Password updated successfully. You can now log in."})


def _target_user(user_id):
    return get_object_or_404(User.objects.select_related("profile"), id=user_id)


class FollowView(APIView):
    """POST follows a user, DELETE unfollows. Both are idempotent."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        target = _target_user(user_id)
        if target.id == request.user.id:
            return Response({"detail": "You cannot follow yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if Block.between(request.user.id, target.id):
            return Response({"detail": "You cannot follow this user."}, status=status.HTTP_403_FORBIDDEN)
        _, created = Follow.objects.get_or_create(follower=request.user, following=target)
        if created:
            notify(target, request.user, Notification.TYPE_FOLLOW,
                   f"{ensure_profile(request.user).username} started following you")
        return Response({"following": True, "followers_count": target.follower_set.count()})

    def delete(self, request, user_id):
        target = _target_user(user_id)
        Follow.objects.filter(follower=request.user, following=target).delete()
        return Response({"following": False, "followers_count": target.follower_set.count()})


class BlockView(APIView):
    """POST blocks a user (and removes follows both ways), DELETE unblocks."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        target = _target_user(user_id)
        if target.id == request.user.id:
            return Response({"detail": "You cannot block yourself."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            Block.objects.get_or_create(blocker=request.user, blocked=target)
            Follow.objects.filter(follower=request.user, following=target).delete()
            Follow.objects.filter(follower=target, following=request.user).delete()
        return Response({"blocked": True})

    def delete(self, request, user_id):
        Block.objects.filter(blocker=request.user, blocked_id=user_id).delete()
        return Response({"blocked": False})


class BlockListView(generics.ListAPIView):
    """Users the caller has blocked (for the settings screen)."""
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(blocked_by__blocker=self.request.user).select_related("profile")
