from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from .models import Transaction


def get_balance(user) -> int:
    return user.transactions.aggregate(total=Sum("amount"))["total"] or 0


@transaction.atomic
def send_gift(*, sender, recipient, gift, room, combo=1):
    """Atomically debit sender, credit recipient, and record the GiftEvent.
    Runs inside one DB transaction + row lock so two simultaneous gift sends
    from the same low-balance user can't both succeed (a real race in the
    prototype's version, which just checked a cached number)."""
    from apps.rooms.models import GiftEvent  # local import avoids circular import

    cost = gift.cost * combo

    # Lock the sender's transaction rows for the duration of this check,
    # so a concurrent request can't read a stale balance.
    locked_balance = (
        Transaction.objects.select_for_update()
        .filter(user=sender)
        .aggregate(total=Sum("amount"))["total"]
        or 0
    )
    if locked_balance < cost:
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
    return event
