"""Phase 5 — social bonds: families, CP / best friends, profile visitors,
voice clips (DM + room voice messages) and scheduled rooms."""
from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Family(models.Model):
    """A club of up to MAX_MEMBERS people with a shared badge, chat and ranking."""
    MAX_MEMBERS = 50
    EMBLEMS = ["crown", "flame", "star", "moon", "heart", "zap", "gem", "leaf", "music", "rocket"]

    name = models.CharField(max_length=40, unique=True)
    tag = models.CharField(max_length=6)                 # short badge text, e.g. "VBR"
    emblem = models.CharField(max_length=16, default="crown")
    description = models.CharField(max_length=200, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FamilyMember(models.Model):
    ROLE_OWNER, ROLE_ELDER, ROLE_MEMBER = "owner", "elder", "member"
    ROLES = [(ROLE_OWNER, "Owner"), (ROLE_ELDER, "Elder"), (ROLE_MEMBER, "Member")]

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="members")
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="family_membership")
    role = models.CharField(max_length=10, choices=ROLES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at"]


class FamilyMessage(models.Model):
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    text = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Bond(models.Model):
    """CP (one per person) or best friend (up to MAX_BFF). Pair stored ordered."""
    KIND_CP, KIND_BFF = "cp", "bff"
    KINDS = [(KIND_CP, "CP"), (KIND_BFF, "Best friend")]
    MAX_BFF = 5
    COST = {KIND_CP: 5200, KIND_BFF: 1314}

    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=4, choices=KINDS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user_a", "user_b")

    def other(self, user_id):
        return self.user_b if self.user_a_id == user_id else self.user_a


class BondRequest(models.Model):
    PENDING, ACCEPTED, DECLINED, CANCELLED = "pending", "accepted", "declined", "cancelled"
    STATUSES = [(s, s) for s in (PENDING, ACCEPTED, DECLINED, CANCELLED)]

    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=4, choices=Bond.KINDS)
    cost = models.PositiveIntegerField(default=0)        # paid up front; refunded unless accepted
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ProfileVisit(models.Model):
    viewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    viewed = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    count = models.PositiveIntegerField(default=1)
    last_at = models.DateTimeField()

    class Meta:
        unique_together = ("viewer", "viewed")
        indexes = [models.Index(fields=["viewed", "last_at"])]


class VoiceClip(models.Model):
    """A recorded voice message, uploaded first and then attached to a DM or room message."""
    MAX_SECONDS = 60
    MAX_BYTES = 2 * 1024 * 1024

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    file = models.CharField(max_length=80)               # name under MEDIA_ROOT/voice/
    seconds = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def url_path(self):
        return f"{settings.MEDIA_URL}voice/{self.file}"


class ScheduledRoom(models.Model):
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scheduled_rooms")
    title = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=20, default="talk")
    starts_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    cancelled = models.BooleanField(default=False)
    room = models.ForeignKey("rooms.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["starts_at"]


class RoomReminder(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    scheduled = models.ForeignKey(ScheduledRoom, on_delete=models.CASCADE, related_name="reminders")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "scheduled")
