from .models import Notification


def notify(user, actor, type_, text, room=None):
    """Create one in-app notification. Never notifies a user about themselves."""
    if actor is not None and actor.pk == user.pk:
        return None
    notification = Notification.objects.create(user=user, actor=actor, type=type_, text=text[:200], room=room)
    _push(user.pk, notification)
    return notification


def _push(user_id, notification):
    # Live badge update for anyone with the app open; polling covers the rest.
    from apps.rooms.realtime import broadcast_to_user

    broadcast_to_user(user_id, "notification.new", {
        "id": notification.id, "type": notification.type, "text": notification.text,
        "room": notification.room_id,
    })


def notify_followers_live(host, room):
    """Tell everyone who follows `host` that they just went live."""
    from apps.accounts.models import Follow

    follower_ids = Follow.objects.filter(following=host).values_list("follower_id", flat=True)
    name = getattr(getattr(host, "profile", None), "username", host.username)
    created = Notification.objects.bulk_create([
        Notification(user_id=fid, actor=host, type=Notification.TYPE_LIVE,
                     text=f"{name} is live: {room.name}"[:200], room=room)
        for fid in follower_ids
    ])
    for n in created:
        _push(n.user_id, n)
