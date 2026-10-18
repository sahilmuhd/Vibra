from .models import Profile


def ensure_profile(user):
    """Users created outside signup (createsuperuser, admin) have no Profile,
    which made /me/ and voice-token 500. Create one on demand."""
    try:
        return user.profile
    except Profile.DoesNotExist:
        base = "".join(c for c in user.get_username().lower() if c.isalnum() or c == "_")[:24] or "user"
        candidate, n = base, 0
        while Profile.objects.filter(username=candidate).exists():
            n += 1
            candidate = f"{base}{n}"
        return Profile.objects.create(
            user=user, username=candidate,
            avatar_url=f"https://api.dicebear.com/7.x/notionists/svg?seed={candidate}",
        )
