from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    GuestLoginView, MeView, PublicProfileView, SignupView,
    PasswordResetRequestView, PasswordResetConfirmView,
)

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", TokenObtainPairView.as_view(), name="login"),
    path("login/refresh/", TokenRefreshView.as_view(), name="login-refresh"),
    path("guest/", GuestLoginView.as_view(), name="guest-login"),
    path("me/", MeView.as_view(), name="me"),
    path("users/<str:username>/", PublicProfileView.as_view(), name="public-profile"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]
