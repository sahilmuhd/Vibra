from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.levels import is_admin
from apps.accounts.serializers import PublicUserSerializer
from apps.rooms.models import Room

from . import services
from .models import StoreItem, UserItem


class StoreView(APIView):
    """Every item for sale, with what the caller owns / wears."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        items = list(StoreItem.objects.filter(is_active=True))
        admin = is_admin(request.user)
        if admin:
            owned = {i.id: services.FOREVER for i in items}
        else:
            owned = {u.item_id: u.expires_at for u in UserItem.objects.filter(user=request.user, expires_at__gt=now)}
        profile = request.user.profile
        worn = {StoreItem.KIND_FRAME: profile.active_frame(now), StoreItem.KIND_MOUNT: profile.active_mount(now)}
        return Response([{
            "id": i.id, "kind": i.kind, "key": i.key, "name": i.name, "price": i.price, "days": i.days,
            "owned_until": owned.get(i.id), "equipped": worn.get(i.kind) == i.key and i.id in owned,
            "free_for_admin": admin,
        } for i in items])


class BuyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "chat"

    def post(self, request):
        item = get_object_or_404(StoreItem, id=request.data.get("item_id"))
        owned = services.buy_item(request.user, item)
        from apps.wallet.services import get_balance
        return Response({"owned_until": owned.expires_at, "balance": get_balance(request.user)},
                        status=status.HTTP_201_CREATED)


class EquipView(APIView):
    """{item_id} wears an owned item; {kind, item_id: null} takes it off."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        item_id = request.data.get("item_id")
        if item_id in (None, ""):
            kind = request.data.get("kind")
            if kind not in (StoreItem.KIND_FRAME, StoreItem.KIND_MOUNT):
                return Response({"detail": "kind must be frame or mount."}, status=status.HTTP_400_BAD_REQUEST)
            services.unequip(request.user, kind)
            return Response({"equipped": None})
        item = get_object_or_404(StoreItem, id=item_id)
        services.equip(request.user, item)
        return Response({"equipped": item.key})


class CheckinView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.checkin_status(request.user))

    def post(self, request):
        return Response(services.claim_checkin(request.user), status=status.HTTP_201_CREATED)


class TasksView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.task_list(request.user))

    def post(self, request):
        return Response(services.claim_task(request.user, str(request.data.get("key", ""))),
                        status=status.HTTP_201_CREATED)


class LeaderboardView(APIView):
    """?board=rich|charm|rooms&period=day|week|month — top 20 by gift value."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        board = request.query_params.get("board", "rich")
        period = request.query_params.get("period", "week")
        if board not in ("rich", "charm", "rooms") or period not in services.PERIODS:
            return Response({"detail": "Unknown board or period."}, status=status.HTTP_400_BAD_REQUEST)
        rows, group = services.leaderboard(board, period)
        ids = [r[group] for r in rows]
        if board == "rooms":
            rooms = {r.id: r for r in Room.objects.filter(id__in=ids).select_related("host__profile")}
            out = [{
                "rank": n, "score": r["score"], "room": {
                    "id": rooms[r[group]].id, "name": rooms[r[group]].name, "is_live": rooms[r[group]].is_live,
                    "host": PublicUserSerializer(rooms[r[group]].host).data,
                },
            } for n, r in enumerate(rows, 1) if r[group] in rooms]
        else:
            users = {u.id: u for u in get_user_model().objects.filter(id__in=ids).select_related("profile")}
            out = [{"rank": n, "score": r["score"], "user": PublicUserSerializer(users[r[group]]).data}
                   for n, r in enumerate(rows, 1) if r[group] in users and hasattr(users[r[group]], "profile")]
        return Response(out)
