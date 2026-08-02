from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Transaction(models.Model):
    """The wallet balance is NEVER stored as a single mutable integer.
    It's always derived by summing signed `amount` values for a user.
    This is the fix for the prototype's `setWallet()` local-storage hole —
    a client can no longer just set their own balance."""

    TYPE_PURCHASE = "purchase"
    TYPE_GIFT_SENT = "gift_sent"
    TYPE_GIFT_RECEIVED = "gift_received"
    TYPE_CHOICES = [
        (TYPE_PURCHASE, "Purchase"),
        (TYPE_GIFT_SENT, "Gift sent"),
        (TYPE_GIFT_RECEIVED, "Gift received"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.IntegerField(help_text="Signed coin amount. Negative = debit.")
    label = models.CharField(max_length=120, blank=True)
    related_gift_event = models.ForeignKey(
        "rooms.GiftEvent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"])]


class CoinPackage(models.Model):
    coins = models.PositiveIntegerField()
    price_inr = models.DecimalField(max_digits=8, decimal_places=2)
    is_best_value = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.coins} coins - ₹{self.price_inr}"


class PaymentOrder(models.Model):
    """One row per Razorpay order, so the webhook has something to reconcile
    against instead of trusting whatever the client claims it paid for."""
    STATUS_CREATED = "created"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payment_orders")
    package = models.ForeignKey(CoinPackage, on_delete=models.PROTECT)
    razorpay_order_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=20,
        default=STATUS_CREATED,
        choices=[(STATUS_CREATED, "Created"), (STATUS_PAID, "Paid"), (STATUS_FAILED, "Failed")],
    )
    created_at = models.DateTimeField(auto_now_add=True)
