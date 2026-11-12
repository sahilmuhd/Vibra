from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Transaction


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def grant_welcome_coins(sender, instance, created, **kwargs):
    """Every new account starts with free coins so people can try gifting
    while real-money purchases are switched off."""
    amount = getattr(settings, "WELCOME_COINS", 0)
    if created and amount > 0:
        Transaction.objects.create(
            user=instance, type=Transaction.TYPE_BONUS, amount=amount, label="Welcome bonus",
        )
