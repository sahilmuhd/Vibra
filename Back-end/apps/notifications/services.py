from .models import Notification


def notify(user, actor, type_, text, room=None):
    """Create one in-app notification. Never notifies a user about themselves."""
    if actor is not None and actor.pk == user.pk:
        return None
    return Notification.objects.create(user=user, actor=actor, type=type_, text=text[:200], room=room)


def notify_followers_live(host, room):
    """Tell everyone who follows `host` that they just went live."""
    from apps.accounts.models import Follow

    follower_ids = Follow.objects.filter(following=host).values_list("follower_id", flat=True)
    name = getattr(getattr(host, "profile", None), "username", host.username)
    Notification.objects.bulk_create([
        Notification(user_id=fid, actor=host, type=Notification.TYPE_LIVE,
                     text=f"{name} is live: {room.name}"[:200], room=room)
        for fid in follower_ids
    ])
