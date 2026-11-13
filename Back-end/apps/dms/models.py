from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Conversation(models.Model):
    """A one-to-one thread. The pair is stored ordered (user_a.id < user_b.id)
    so there is exactly one row per pair of people."""
    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user_a", "user_b")
        ordering = ["-updated_at"]

    def other(self, user_id):
        return self.user_b if self.user_a_id == user_id else self.user_a


class DirectMessage(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    text = models.CharField(max_length=1000, blank=True)
    voice = models.ForeignKey("social.VoiceClip", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"])]
