"""Phase 6 — games inside rooms. No betting: players never stake coins.
Quiz / guess-the-song prizes are paid up front by the host and go to winners
(or straight back to the host if nobody wins)."""
from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class RoomGame(models.Model):
    KIND_QUIZ, KIND_GUESS = "quiz", "guess"
    KINDS = [(KIND_QUIZ, "Quiz"), (KIND_GUESS, "Guess the song")]
    OPEN, DONE = "open", "done"

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="games")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=8, choices=KINDS)
    question = models.CharField(max_length=200)
    options = models.JSONField(default=list, blank=True)     # quiz choices
    answer = models.CharField(max_length=100)                 # quiz: index as text; guess: normalised answer
    answer_display = models.CharField(max_length=100, blank=True)
    prize = models.PositiveIntegerField(default=0)
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=6, default=OPEN)
    winners = models.JSONField(default=list, blank=True)       # user ids
    prize_each = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class GameAnswer(models.Model):
    game = models.ForeignKey(RoomGame, on_delete=models.CASCADE, related_name="answers")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    answer = models.CharField(max_length=100)
    correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
