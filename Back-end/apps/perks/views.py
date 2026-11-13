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
        admin = is_admin(request.user)
        items = list(StoreItem.objects.filter(is_active=True).select_related("event"))
        if admin:
            owned = {i.id: services.FOREVER for i in items}
        else:
            owned = {u.item_id: u.expires_at for u in UserItem.objects.filter(user=request.user, expires_at__gt=now)}
        # Event items show while their event runs (or if already owned).
        items = [i for i in items if not i.event_id or i.event.is_live(now) or i.id in owned]
        profile = request.user.profile
        worn = {StoreItem.KIND_FRAME: profile.active_frame(now), StoreItem.KIND_MOUNT: profile.active_mount(now)}
        return Response([{
            "id": i.id, "kind": i.kind, "key": i.key, "name": i.name, "price": i.price, "days": i.days,
            "owned_until": owned.get(i.id), "equipped": worn.get(i.kind) == i.key and i.id in owned,
            "free_for_admin": admin,
            "event": ({"key": i.event.key, "name": i.event.name, "ends_at": i.event.ends_at} if i.event_id else None),
        } for i in items])


class EventsView(APIView):
    """Live + upcoming seasonal events, each with its limited items and ranking."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .models import SeasonEvent
        now = timezone.now()
        out = []
        for ev in SeasonEvent.objects.filter(is_active=True, ends_at__gt=now).order_by("starts_at")[:3]:
            live = ev.is_live(now)
            ranking = []
            if live:
                rows = services.event_ranking(ev)
                users = {u.id: u for u in get_user_model().objects.filter(id__in=[r["sender"] for r in rows]).select_related("profile")}
                ranking = [{"rank": n, "score": r["score"], "user": PublicUserSerializer(users[r["sender"]]).data}
                           for n, r in enumerate(rows, 1) if r["sender"] in users and hasattr(users[r["sender"]], "profile")]
            out.append({
                "key": ev.key, "name": ev.name, "tagline": ev.tagline, "style": ev.style,
                "starts_at": ev.starts_at, "ends_at": ev.ends_at, "live": live,
                "item_ids": list(ev.items.filter(is_active=True).values_list("id", flat=True)),
                "ranking": ranking,
            })
        return Response(out)


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
        if board == "families" and period in services.PERIODS:
            from datetime import timedelta

            from apps.social.models import Family
            from apps.social.services import family_scores
            since = timezone.now() - timedelta(days=services.PERIODS[period])
            fams = family_scores(Family.objects.all(), since).filter(score__gt=0).order_by("-score")[:20]
            return Response([{"rank": n, "score": f.score, "family": {
                "id": f.id, "name": f.name, "tag": f.tag, "emblem": f.emblem, "members": f.member_count}}
                for n, f in enumerate(fams, 1)])
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
