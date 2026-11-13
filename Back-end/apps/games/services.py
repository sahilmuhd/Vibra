import random
import re
import unicodedata
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from apps.accounts.serializers import PublicUserSerializer
from apps.rooms.models import RoomParticipant, Seat
from apps.rooms.realtime import broadcast_to_room
from apps.rooms.services import can_moderate, user_in_room
from apps.wallet.models import Transaction
from apps.wallet.services import get_balance

from .models import GameAnswer, RoomGame

MAX_PRIZE = 10_000
GUESS_ATTEMPTS = 3
rng = random.SystemRandom()

TRUTHS = [
    "What's the most embarrassing song you secretly love?",
    "Who in this room would you call at 3 AM?",
    "What's a habit you're trying to break?",
    "What's the best compliment you've ever received?",
    "What's your most unpopular opinion?",
    "What was your first impression of the host?",
    "What's something you've never told anyone here?",
    "Which emoji describes your week, and why?",
    "What's the silliest thing you've cried about?",
    "If you could swap lives with someone here for a day, who?",
    "What's your biggest fear?",
    "What's the last lie you told?",
]
DARES = [
    "Sing the chorus of your favourite song.",
    "Do your best impression of someone in this room.",
    "Speak in an accent for the next two minutes.",
    "Say something nice about every person on the mic.",
    "Tell a joke — if nobody laughs, tell another!",
    "Talk like a news reporter about your day.",
    "Describe your outfit like a fashion show host.",
    "Make the weirdest sound you can.",
    "Rap the next sentence you say.",
    "Laugh like a villain for five seconds.",
    "Compliment the host in three different languages.",
    "Tell us your best pickup line.",
]


def normalise(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def _rate(key, seconds):
    if not cache.add(key, 1, seconds):
        raise Throttled(wait=seconds, detail="Slow down a little.")


def _user(u):
    return PublicUserSerializer(u).data


def require_in_room(room, user):
    if not room.is_live:
        raise ValidationError("This room has ended.")
    if not user_in_room(room, user):
        raise PermissionDenied("Join the room first.")


# ------------------------------------------------------------------ dice + wheel
def roll_dice(room, user):
    require_in_room(room, user)
    _rate(f"dice:{room.id}:{user.id}", 3)
    value = rng.randint(1, 6)
    broadcast_to_room(room.id, "game.dice", {"user": _user(user), "value": value})
    return value


def spin_wheel(room, user, mode):
    require_in_room(room, user)
    if not can_moderate(room, user):
        raise PermissionDenied("Only the host or a moderator can spin the wheel.")
    _rate(f"wheel:{room.id}", 5)
    User = get_user_model()
    seated = list(Seat.objects.filter(room=room, user__isnull=False).values_list("user_id", flat=True))
    pool = seated if len(seated) >= 2 else list(RoomParticipant.objects.filter(room=room).values_list("user_id", flat=True))
    if len(pool) < 2:
        raise ValidationError("Need at least two people in the room to spin.")
    users = {u.id: u for u in User.objects.filter(id__in=pool).select_related("profile")}
    candidates = [users[i] for i in pool if i in users][:12]
    target = rng.choice(candidates)
    kind = mode if mode in ("truth", "dare") else rng.choice(["truth", "dare"])
    prompt = rng.choice(TRUTHS if kind == "truth" else DARES)
    payload = {"by": _user(user), "candidates": [_user(u) for u in candidates], "target": _user(target),
               "kind": kind, "prompt": prompt}
    broadcast_to_room(room.id, "game.wheel", payload)
    return payload


# ------------------------------------------------------------------ quiz / guess the song
def public_game(game, viewer=None):
    data = {
        "id": game.id, "kind": game.kind, "question": game.question, "options": game.options,
        "prize": game.prize, "ends_at": game.ends_at, "status": game.status,
        "created_by": _user(game.created_by),
    }
    if viewer is not None:
        mine = list(game.answers.filter(user=viewer))
        data["my_answers"] = len(mine)
        data["my_answer"] = mine[0].answer if game.kind == RoomGame.KIND_QUIZ and mine else None
    if game.status == RoomGame.DONE:
        data.update(result_payload(game))
    return data


def result_payload(game):
    User = get_user_model()
    winners = User.objects.filter(id__in=game.winners).select_related("profile")
    by_id = {u.id: u for u in winners}
    return {"winners": [_user(by_id[i]) for i in game.winners if i in by_id], "prize_each": game.prize_each,
            "answer": game.answer_display}


@transaction.atomic
def start_game(room, user, data):
    require_in_room(room, user)
    if not can_moderate(room, user):
        raise PermissionDenied("Only the host or a moderator can start a game.")
    settle_expired(room)
    if RoomGame.objects.filter(room=room, status=RoomGame.OPEN).exists():
        raise ValidationError("A game is already running in this room.")
    kind = data.get("kind")
    question = " ".join(str(data.get("question") or "").split())[:200]
    try:
        prize = int(data.get("prize") or 0)
        seconds = int(data.get("seconds") or 30)
    except (TypeError, ValueError):
        raise ValidationError("Prize and time must be numbers.")
    if not 0 <= prize <= MAX_PRIZE:
        raise ValidationError({"prize": f"Prize can be 0-{MAX_PRIZE:,} coins."})
    if kind == RoomGame.KIND_QUIZ:
        options = [" ".join(str(o).split())[:60] for o in (data.get("options") or []) if str(o).strip()]
        if not 2 <= len(options) <= 4:
            raise ValidationError({"options": "Give 2 to 4 answers."})
        try:
            correct = int(data.get("correct"))
        except (TypeError, ValueError):
            correct = -1
        if not 0 <= correct < len(options):
            raise ValidationError({"correct": "Mark the right answer."})
        if len(question) < 3:
            raise ValidationError({"question": "Write a question."})
        seconds = max(10, min(60, seconds))
        answer, display = str(correct), options[correct]
    elif kind == RoomGame.KIND_GUESS:
        options = []
        display = " ".join(str(data.get("answer") or "").split())[:100]
        answer = normalise(display)
        if len(answer) < 2:
            raise ValidationError({"answer": "Type the song title."})
        question = question or "Guess the song that's playing!"
        seconds = max(15, min(180, seconds))
    else:
        raise ValidationError({"kind": "Choose quiz or guess."})
    if prize:
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if get_balance(user) < prize:
            raise ValidationError({"prize": "You don't have enough coins for that prize."})
        Transaction.objects.create(user=user, type=Transaction.TYPE_GAME, amount=-prize,
                                   label=f"Prize for {'quiz' if kind == RoomGame.KIND_QUIZ else 'guess the song'}")
    game = RoomGame.objects.create(room=room, created_by=user, kind=kind, question=question, options=options,
                                   answer=answer, answer_display=display, prize=prize,
                                   ends_at=timezone.now() + timedelta(seconds=seconds))
    transaction.on_commit(lambda: broadcast_to_room(room.id, "game.start", public_game(game)))
    return game


@transaction.atomic
def answer_game(room, user, game_id, answer):
    require_in_room(room, user)
    game = RoomGame.objects.select_for_update().filter(id=game_id, room=room).first()
    if game is None:
        raise ValidationError("Game not found.")
    if game.status != RoomGame.OPEN or game.ends_at <= timezone.now():
        # (settled by the timer / `finish` — raising here would roll a settle back)
        raise ValidationError("Time's up!")
    if game.created_by_id == user.id:
        raise ValidationError("You set this game — let the others answer.")
    tries = game.answers.filter(user=user).count()
    if game.kind == RoomGame.KIND_QUIZ:
        if tries:
            raise ValidationError("You already answered.")
        correct = str(answer) == game.answer
        GameAnswer.objects.create(game=game, user=user, answer=str(answer)[:100], correct=correct)
        return {"correct": None, "locked": True}          # revealed when the timer ends
    if tries >= GUESS_ATTEMPTS:
        raise ValidationError("No guesses left.")
    correct = normalise(answer) == game.answer
    GameAnswer.objects.create(game=game, user=user, answer=str(answer)[:100], correct=correct)
    if correct:
        settle(game)                                       # first right guess wins
    return {"correct": correct, "left": GUESS_ATTEMPTS - tries - 1}


def settle(game):
    """Pay winners (or refund the host) exactly once. Caller may or may not hold the lock."""
    with transaction.atomic():
        game = RoomGame.objects.select_for_update().get(pk=game.pk)
        if game.status == RoomGame.DONE:
            return game
        right = game.answers.filter(correct=True).order_by("created_at", "id")
        if game.kind == RoomGame.KIND_GUESS:
            right = right[:1]
        winners = list(dict.fromkeys(right.values_list("user_id", flat=True)))
        each = game.prize // len(winners) if winners and game.prize else 0
        for uid in winners:
            if each:
                Transaction.objects.create(user_id=uid, type=Transaction.TYPE_GAME, amount=each,
                                           label="Game prize")
        leftover = game.prize - each * len(winners)
        if leftover:
            Transaction.objects.create(user=game.created_by, type=Transaction.TYPE_GAME, amount=leftover,
                                       label="Game prize returned")
        game.status, game.winners, game.prize_each = RoomGame.DONE, winners, each
        game.save(update_fields=["status", "winners", "prize_each"])
        payload = {"id": game.id, "kind": game.kind, "question": game.question, **result_payload(game)}
        room_id = game.room_id
        transaction.on_commit(lambda: broadcast_to_room(room_id, "game.result", payload))
    return game


def settle_expired(room=None):
    qs = RoomGame.objects.filter(status=RoomGame.OPEN, ends_at__lte=timezone.now())
    if room is not None:
        qs = qs.filter(room=room)
    n = 0
    for g in list(qs):
        settle(g)
        n += 1
    # A room that ended mid-game refunds its host.
    for g in list(RoomGame.objects.filter(status=RoomGame.OPEN, room__is_live=False)):
        settle(g)
        n += 1
    return n
