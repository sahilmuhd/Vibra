import uuid

from django.contrib.auth import get_user_model
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Profile
from .serializers import ProfileSerializer, SignupSerializer

User = get_user_model()


class LoginSerializer(TokenObtainPairSerializer):
    """Accepts a username OR an email, case-insensitively (the login form says
    "Email or username"; signup stores usernames lowercased)."""

    def validate(self, attrs):
        ident = (attrs.get(self.username_field) or "").strip()
        user = (
            User.objects.filter(username__iexact=ident).first()
            or User.objects.filter(email__iexact=ident).first()
        )
        if user:
            attrs[self.username_field] = user.get_username()
        return super().validate(attrs)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class SignupView(APIView):
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
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        suffix = uuid.uuid4().hex[:8]
        username = f"guest{suffix}"
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
        return self.request.user.profile


class PublicProfileView(generics.RetrieveAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "username"
    queryset = Profile.objects.all()
