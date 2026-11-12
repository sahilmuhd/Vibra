from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from apps.notifications.models import Notification
from apps.notifications.services import notify

from .models import PaymentOrder, Transaction


def get_balance(user) -> int:
    return user.transactions.aggregate(total=Sum("amount"))["total"] or 0


@transaction.atomic
def send_gift(*, sender, recipient, gift, room, combo=1):
    """Atomically debit sender, credit recipient, and record the GiftEvent.

    The sender's *user row* is locked for the duration (PostgreSQL rejects
    `SELECT ... FOR UPDATE` combined with an aggregate, so the ledger rows
    themselves can't be the lock). Two simultaneous sends from the same
    low-balance user therefore serialise and the second sees the debit."""
    from apps.rooms.models import GiftEvent  # local import avoids circular import
    from apps.rooms.services import user_in_room

    if sender.pk == recipient.pk:
        raise ValidationError("You cannot send a gift to yourself.")
    if not room.is_live:
        raise ValidationError("This room has ended.")
    if not user_in_room(room, sender):
        raise ValidationError("Join the room before sending gifts.")
    if not user_in_room(room, recipient):
        raise ValidationError("The recipient is not in this room.")

    cost = gift.cost * combo

    get_user_model().objects.select_for_update().get(pk=sender.pk)
    if get_balance(sender) < cost:
        raise ValidationError("Insufficient coins.")

    event = GiftEvent.objects.create(
        room=room, sender=sender, recipient=recipient, gift=gift, combo=combo
    )
    Transaction.objects.create(
        user=sender, type=Transaction.TYPE_GIFT_SENT, amount=-cost,
        label=f"Sent {gift.name} x{combo}", related_gift_event=event,
    )
    Transaction.objects.create(
        user=recipient, type=Transaction.TYPE_GIFT_RECEIVED, amount=cost,
        label=f"Received {gift.name} x{combo} from {sender}", related_gift_event=event,
    )
    _add_xp(sender, wealth=cost)
    _add_xp(recipient, charm=cost)
    notify(recipient, sender, Notification.TYPE_GIFT,
           f"{sender} sent you {gift.name}" + (f" x{combo}" if combo > 1 else ""), room=room)
    return event


def _add_xp(user, wealth=0, charm=0):
    """Gift value counts toward levels: spent -> wealth (and VIP), received -> charm."""
    from django.db.models import F

    from apps.accounts.levels import level_for
    from apps.accounts.models import Profile
    from apps.accounts.profiles import ensure_profile

    ensure_profile(user)
    Profile.objects.filter(user=user).update(wealth_xp=F("wealth_xp") + wealth, charm_xp=F("charm_xp") + charm)
    profile = Profile.objects.get(user=user)
    lvl = level_for(profile.wealth_xp)
    if profile.level != lvl:
        Profile.objects.filter(pk=profile.pk).update(level=lvl)
    if hasattr(user, "_state") and hasattr(user, "profile"):
        user.profile.refresh_from_db()


@transaction.atomic
def credit_paid_order(razorpay_order_id):
    """Marks an order paid and credits the coins exactly once, even if
    Razorpay delivers the webhook several times concurrently.
    Returns True if coins were credited, False if already processed.
    Raises PaymentOrder.DoesNotExist for an unknown order."""
    order = (
        PaymentOrder.objects.select_for_update()
        .select_related("package", "user")
        .get(razorpay_order_id=razorpay_order_id)
    )
    if order.status == PaymentOrder.STATUS_PAID:
        return False
    order.status = PaymentOrder.STATUS_PAID
    order.save(update_fields=["status"])
    Transaction.objects.create(
        user=order.user,
        type=Transaction.TYPE_PURCHASE,
        amount=order.package.coins,
        label=f"Purchased {order.package.coins} coins",
    )
    return True
