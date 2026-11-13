from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rooms.models import Room
from apps.wallet.services import get_balance

from . import services
from .models import RoomGame


class GameView(APIView):
    """/api/games/rooms/<id>/<action>/
    GET  current            -> the open game (or the last result) for this room
    POST dice               -> roll 1-6 (anyone in the room)
    POST wheel {mode}       -> truth / dare / random (host or moderator)
    POST start {kind,...}   -> quiz or guess-the-song (host or moderator, prize paid up front)
    POST answer {game_id, answer}
    POST finish {game_id}   -> settle once the timer has run out (any client may call)
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "chat"

    def get(self, request, room_id, action):
        room = get_object_or_404(Room, id=room_id)
        if action != "current":
            return Response({"detail": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        services.require_in_room(room, request.user)
        services.settle_expired(room)
        game = RoomGame.objects.filter(room=room).select_related("created_by__profile").first()
        return Response(services.public_game(game, request.user) if game else None)

    def post(self, request, room_id, action):
        room = get_object_or_404(Room, id=room_id)
        d = request.data
        if action == "dice":
            return Response({"value": services.roll_dice(room, request.user)})
        if action == "wheel":
            return Response(services.spin_wheel(room, request.user, d.get("mode")))
        if action == "start":
            game = services.start_game(room, request.user, d)
            return Response({**services.public_game(game), "balance": get_balance(request.user)},
                            status=status.HTTP_201_CREATED)
        if action == "answer":
            res = services.answer_game(room, request.user, d.get("game_id"), d.get("answer"))
            return Response({**res, "balance": get_balance(request.user)})
        if action == "finish":
            game = get_object_or_404(RoomGame, id=d.get("game_id"), room=room)
            services.settle_expired(room)
            game.refresh_from_db()
            return Response(services.public_game(game, request.user))
        return Response({"detail": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
