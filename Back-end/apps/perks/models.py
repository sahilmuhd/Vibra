from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class StoreItem(models.Model):
    """Something you can buy with coins for a few days: an avatar frame or a
    mount (the vehicle that plays when you enter a room). `key` is what the
    client draws; the artwork lives in the frontend."""
    KIND_FRAME = "frame"
    KIND_MOUNT = "mount"
    KIND_THEME = "theme"   # a room background the owner can apply to rooms they host
    KINDS = [(KIND_FRAME, "Avatar frame"), (KIND_MOUNT, "Mount"), (KIND_THEME, "Room theme")]
    WEARABLE = (KIND_FRAME, KIND_MOUNT)

    kind = models.CharField(max_length=10, choices=KINDS)
    key = models.CharField(max_length=32)
    name = models.CharField(max_length=40)
    price = models.PositiveIntegerField(help_text="Coins per rental period")
    days = models.PositiveSmallIntegerField(default=7)
    sort = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("kind", "key")
        ordering = ["kind", "sort", "price"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name}"


class UserItem(models.Model):
    """An item a user owns until `expires_at` (buying again extends it)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(StoreItem, on_delete=models.CASCADE, related_name="+")
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = ("user", "item")


class DailyCheckin(models.Model):
    """One row per day a user claimed the daily reward; `streak` is 1..7."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="checkins")
    day = models.DateField()
    streak = models.PositiveSmallIntegerField()
    coins = models.PositiveIntegerField()

    class Meta:
        unique_together = ("user", "day")
        ordering = ["-day"]


class TaskClaim(models.Model):
    """A daily task reward that has been collected."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="task_claims")
    key = models.CharField(max_length=32)
    day = models.DateField()
    coins = models.PositiveIntegerField()

    class Meta:
        unique_together = ("user", "key", "day")
