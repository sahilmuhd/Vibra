from django.urls import path

from .views import (
    JoinRoomView,
    LeaveRoomView,
    LeaveSeatView,
    MessageListCreateView,
    RaiseHandView,
    RoomDetailView,
    RoomListCreateView,
    TakeSeatView,
    ToggleMuteView,
)
from .voice import VoiceTokenView

urlpatterns = [
    path("", RoomListCreateView.as_view(), name="room-list-create"),
    path("<int:pk>/", RoomDetailView.as_view(), name="room-detail"),
    path("<int:room_id>/join/", JoinRoomView.as_view(), name="room-join"),
    path("<int:room_id>/leave/", LeaveRoomView.as_view(), name="room-leave"),
    path("<int:room_id>/seats/<int:position>/take/", TakeSeatView.as_view(), name="seat-take"),
    path("<int:room_id>/seats/<int:position>/leave/", LeaveSeatView.as_view(), name="seat-leave"),
    path("<int:room_id>/seats/<int:position>/mute/", ToggleMuteView.as_view(), name="seat-mute"),
    path("<int:room_id>/hand-raise/", RaiseHandView.as_view(), name="hand-raise"),
    path("<int:room_id>/messages/", MessageListCreateView.as_view(), name="room-messages"),
    path("<int:room_id>/voice-token/", VoiceTokenView.as_view(), name="voice-token"),
]
