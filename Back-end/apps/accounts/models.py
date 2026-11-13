from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Extra Vibra-specific fields on top of Django's built-in User.
    Keeping this as a separate model (instead of a custom User) means you
    can swap auth providers later without touching this table.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    username = models.CharField(max_length=30, unique=True)
    avatar_url = models.URLField(blank=True)
    bio = models.CharField(max_length=160, blank=True)
    country = models.CharField(max_length=64, blank=True)
    level = models.PositiveIntegerField(default=1)
    is_guest = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Coin totals behind levels/VIP (see accounts/levels.py). `level` above
    # mirrors the wealth level so older clients keep showing a sensible "Lv".
    wealth_xp = models.BigIntegerField(default=0)
    charm_xp = models.BigIntegerField(default=0)

    # Equipped store items (key + when it runs out); see apps/perks.
    frame_key = models.CharField(max_length=32, blank=True)
    frame_until = models.DateTimeField(null=True, blank=True)
    mount_key = models.CharField(max_length=32, blank=True)
    mount_until = models.DateTimeField(null=True, blank=True)

    # Phase 5 (apps/social): copies of family + CP so badges cost no extra queries.
    family_id = models.PositiveIntegerField(null=True, blank=True)
    family_tag = models.CharField(max_length=6, blank=True)
    cp_partner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    cp_name = models.CharField(max_length=30, blank=True)
    visitors_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.username

    def active_frame(self, now=None):
        from django.utils import timezone
        now = now or timezone.now()
        return self.frame_key if self.frame_key and self.frame_until and self.frame_until > now else ""

    def active_mount(self, now=None):
        from django.utils import timezone
        now = now or timezone.now()
        return self.mount_key if self.mount_key and self.mount_until and self.mount_until > now else ""


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following_set"
    )
    following = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follower_set"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("follower", "following")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("following")),
                name="cannot_follow_self",
            )
        ]


class Block(models.Model):
    """`blocker` no longer sees `blocked`'s chat messages, and `blocked` cannot
    join rooms that `blocker` hosts."""
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_made"
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocked_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def between(cls, a_id, b_id) -> bool:
        """True if either user has blocked the other."""
        return cls.objects.filter(
            models.Q(blocker_id=a_id, blocked_id=b_id) | models.Q(blocker_id=b_id, blocked_id=a_id)
        ).exists()

    class Meta:
        unique_together = ("blocker", "blocked")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")),
                name="cannot_block_self",
            )
        ]
