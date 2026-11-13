from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.profiles import ensure_profile
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .models import DailyCheckin, StoreItem, TaskClaim, UserItem

from apps.accounts.levels import is_admin

# What "forever" means for the admin's free items.
FOREVER = timezone.make_aware(datetime(2099, 12, 31))

# Day 1..7 of a check-in streak; day 7 repeats once the streak is complete.
DAILY_REWARDS = [50, 80, 100, 150, 200, 300, 500]


def today():
    return timezone.localdate()


def day_start(d):
    return timezone.make_aware(datetime.combine(d, time.min))


# ------------------------------------------------------------------ store
@transaction.atomic
def buy_item(user, item):
    if not item.is_active:
        raise ValidationError("This item is no longer sold.")
    if is_admin(user):
        # The main admin owns everything already: "buying" just puts it on.
        owned, _ = UserItem.objects.update_or_create(user=user, item=item, defaults={"expires_at": FOREVER})
        if item.kind in StoreItem.WEARABLE:
            equip(user, item, owned)
        return owned
    get_user_model().objects.select_for_update().get(pk=user.pk)  # serialise spends, like gifts
    if get_balance(user) < item.price:
        raise ValidationError("Not enough coins.")
    now = timezone.now()
    owned, _ = UserItem.objects.select_for_update().get_or_create(
        user=user, item=item, defaults={"expires_at": now},
    )
    owned.expires_at = max(owned.expires_at, now) + timedelta(days=item.days)
    owned.save(update_fields=["expires_at"])
    Transaction.objects.create(user=user, type=Transaction.TYPE_SHOP, amount=-item.price,
                               label=f"Bought {item.name} ({item.days} days)")
    if item.kind not in StoreItem.WEARABLE:
        return owned          # themes are applied per room, not worn
    profile = ensure_profile(user)
    # Auto-equip if nothing of this kind is active, or if it is the one already worn.
    current = profile.active_frame() if item.kind == StoreItem.KIND_FRAME else profile.active_mount()
    if not current or current == item.key:
        equip(user, item, owned)
    return owned


def equip(user, item, owned=None):
    if item.kind not in StoreItem.WEARABLE:
        raise ValidationError("Themes are applied from your room's settings.")
    profile = ensure_profile(user)
    if is_admin(user) and owned is None:
        owned, _ = UserItem.objects.update_or_create(user=user, item=item, defaults={"expires_at": FOREVER})
    owned = owned or UserItem.objects.filter(user=user, item=item, expires_at__gt=timezone.now()).first()
    if owned is None or owned.expires_at <= timezone.now():
        raise ValidationError("Buy this item first.")
    if item.kind == StoreItem.KIND_FRAME:
        profile.frame_key, profile.frame_until = item.key, owned.expires_at
        profile.save(update_fields=["frame_key", "frame_until"])
    else:
        profile.mount_key, profile.mount_until = item.key, owned.expires_at
        profile.save(update_fields=["mount_key", "mount_until"])


def unequip(user, kind):
    profile = ensure_profile(user)
    if kind == StoreItem.KIND_FRAME:
        profile.frame_key, profile.frame_until = "", None
        profile.save(update_fields=["frame_key", "frame_until"])
    else:
        profile.mount_key, profile.mount_until = "", None
        profile.save(update_fields=["mount_key", "mount_until"])


def owns_theme(user, key):
    """Room themes: '' (the starry default) is free; others must be owned (admin owns all)."""
    if not key:
        return True
    item = StoreItem.objects.filter(kind=StoreItem.KIND_THEME, key=key, is_active=True).first()
    if item is None:
        return False
    if is_admin(user):
        return True
    return UserItem.objects.filter(user=user, item=item, expires_at__gt=timezone.now()).exists()


# ------------------------------------------------------------------ daily check-in
def checkin_status(user):
    d = today()
    last = DailyCheckin.objects.filter(user=user).order_by("-day").first()
    claimed_today = bool(last and last.day == d)
    if claimed_today:
        streak = last.streak
    elif last and last.day == d - timedelta(days=1) and last.streak < len(DAILY_REWARDS):
        streak = last.streak  # continuing tomorrow's claim from here
    else:
        streak = 0
    next_day = streak if claimed_today else streak + 1
    return {
        "claimed_today": claimed_today,
        "streak": streak,                       # days collected in the current run
        "today_day": min(next_day, len(DAILY_REWARDS)) if not claimed_today else streak,
        "rewards": DAILY_REWARDS,
    }


@transaction.atomic
def claim_checkin(user):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    status = checkin_status(user)
    if status["claimed_today"]:
        raise ValidationError("Already claimed today. Come back tomorrow!")
    day_n = status["today_day"]
    coins = DAILY_REWARDS[day_n - 1]
    DailyCheckin.objects.create(user=user, day=today(), streak=day_n, coins=coins)
    Transaction.objects.create(user=user, type=Transaction.TYPE_REWARD, amount=coins,
                               label=f"Daily check-in (day {day_n})")
    return {"day": day_n, "coins": coins, "balance": get_balance(user)}


# ------------------------------------------------------------------ daily tasks
def _count_today(user, key):
    from apps.accounts.models import Follow
    from apps.dms.models import DirectMessage
    from apps.rooms.models import GiftEvent, Message, Room

    since = day_start(today())
    if key == "gift":
        return GiftEvent.objects.filter(sender=user, created_at__gte=since).count()
    if key == "chat":
        return Message.objects.filter(user=user, created_at__gte=since).count()
    if key == "follow":
        return Follow.objects.filter(follower=user, created_at__gte=since).count()
    if key == "host":
        return Room.objects.filter(host=user, created_at__gte=since).count()
    if key == "dm":
        return DirectMessage.objects.filter(sender=user, created_at__gte=since).count()
    return 0


# key, title, goal, coins, where "Go" takes you on the client
TASKS = [
    ("chat", "Send 5 messages in rooms", 5, 20, "rooms"),
    ("gift", "Send a gift", 1, 30, "rooms"),
    ("follow", "Follow someone new", 1, 20, "rooms"),
    ("host", "Host a room", 1, 30, "create"),
    ("dm", "Send a direct message", 1, 10, "messages"),
]


def task_list(user):
    claimed = set(TaskClaim.objects.filter(user=user, day=today()).values_list("key", flat=True))
    rows = []
    for key, title, goal, coins, go in TASKS:
        progress = min(goal, _count_today(user, key))
        rows.append({"key": key, "title": title, "goal": goal, "progress": progress, "coins": coins,
                     "done": progress >= goal, "claimed": key in claimed, "go": go})
    return rows


@transaction.atomic
def claim_task(user, key):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    task = next((t for t in task_list(user) if t["key"] == key), None)
    if task is None:
        raise ValidationError("Unknown task.")
    if task["claimed"]:
        raise ValidationError("Already collected today.")
    if not task["done"]:
        raise ValidationError("Finish the task first.")
    TaskClaim.objects.create(user=user, key=key, day=today(), coins=task["coins"])
    Transaction.objects.create(user=user, type=Transaction.TYPE_REWARD, amount=task["coins"],
                               label=f"Task: {task['title']}")
    return {"coins": task["coins"], "balance": get_balance(user)}


# ------------------------------------------------------------------ leaderboards
PERIODS = {"day": 1, "week": 7, "month": 30}


def leaderboard(board, period, limit=20):
    from apps.rooms.models import GiftEvent

    since = timezone.now() - timedelta(days=PERIODS[period])
    events = GiftEvent.objects.filter(created_at__gte=since)
    value = Sum(F("gift__cost") * F("combo"))
    group = {"rich": "sender", "charm": "recipient", "rooms": "room"}[board]
    return list(events.values(group).annotate(score=value).order_by("-score")[:limit]), group
