from django.urls import path

from .views import GameView

urlpatterns = [
    path("rooms/<int:room_id>/<str:action>/", GameView.as_view(), name="room-game"),
]
