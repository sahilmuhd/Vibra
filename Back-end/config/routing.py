from django.urls import re_path

from apps.rooms.consumers import RoomConsumer, UserConsumer

websocket_urlpatterns = [
    re_path(r"ws/rooms/(?P<room_id>\d+)/$", RoomConsumer.as_asgi()),
    re_path(r"ws/me/$", UserConsumer.as_asgi()),
]
