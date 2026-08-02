from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Room(models.Model):
    CATEGORY_CHOICES = [
        ("music", "Music"), ("gaming", "Gaming"), ("talk", "Talk"),
        ("language", "Language"), ("friends", "Friends"), ("entertainment", "Entertainment"),
    ]
    name = models.CharField(max_length=80)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=200, blank=True)
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hosted_rooms")
    thumbnail_seed = models.CharField(max_length=40, blank=True)
    seat_count = models.PositiveSmallIntegerField(default=9)
    is_live = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # LiveKit (or Agora) room name — kept separate from the PK so the voice
    # provider's room identity can be rotated without touching this row.
    voice_room_name = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.name


class Seat(models.Model):
    """A room's mic grid. One row per seat position, created up-front when
    the Room is created (seat_count rows, position 0..N-1)."""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="seats")
    position = models.PositiveSmallIntegerField()
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    is_muted = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        unique_together = ("room", "position")
        ordering = ["position"]


class HandRaise(models.Model):
    """Queue of users requesting a seat — the host approves/declines these."""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="hand_raises")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("room", "user")
        ordering = ["created_at"]


class Message(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    text = models.CharField(max_length=500)
    reply_to = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Gift(models.Model):
    name = models.CharField(max_length=40)
    emoji = models.CharField(max_length=8)
    cost = models.PositiveIntegerField()
    animation_key = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return self.name


class GiftEvent(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="gift_events")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="gifts_sent")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="gifts_received")
    gift = models.ForeignKey(Gift, on_delete=models.PROTECT)
    combo = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
