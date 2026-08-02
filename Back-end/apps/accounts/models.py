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

    def __str__(self):
        return self.username


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
