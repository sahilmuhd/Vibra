from django.urls import path

from .views import (
    EndRoomView,
    ForceMuteSeatView,
    JoinRoomView,
    KickParticipantView,
    LeaveRoomView,
    LeaveSeatView,
    LockSeatView,
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
    path("<int:room_id>/end/", EndRoomView.as_view(), name="room-end"),
    path("<int:room_id>/kick/", KickParticipantView.as_view(), name="participant-kick"),
    path("<int:room_id>/seats/<int:position>/take/", TakeSeatView.as_view(), name="seat-take"),
    path("<int:room_id>/seats/<int:position>/leave/", LeaveSeatView.as_view(), name="seat-leave"),
    path("<int:room_id>/seats/<int:position>/mute/", ToggleMuteView.as_view(), name="seat-mute"),
    path("<int:room_id>/seats/<int:position>/force-mute/", ForceMuteSeatView.as_view(), name="seat-force-mute"),
    path("<int:room_id>/seats/<int:position>/lock/", LockSeatView.as_view(), name="seat-lock"),
    path("<int:room_id>/hand-raise/", RaiseHandView.as_view(), name="hand-raise"),
    path("<int:room_id>/messages/", MessageListCreateView.as_view(), name="room-messages"),
    path("<int:room_id>/voice-token/", VoiceTokenView.as_view(), name="voice-token"),
]
