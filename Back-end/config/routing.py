from django.urls import re_path

from apps.rooms.consumers import RoomConsumer

websocket_urlpatterns = [
    re_path(r"ws/rooms/(?P<room_id>\d+)/$", RoomConsumer.as_asgi()),
]
