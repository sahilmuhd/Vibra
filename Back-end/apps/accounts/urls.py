from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import GuestLoginView, LoginView, MeView, PublicProfileView, SignupView

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    path("login/refresh/", TokenRefreshView.as_view(), name="login-refresh"),
    path("guest/", GuestLoginView.as_view(), name="guest-login"),
    path("me/", MeView.as_view(), name="me"),
    path("users/<str:username>/", PublicProfileView.as_view(), name="public-profile"),
]
