from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.wallet.models import Transaction


class Command(BaseCommand):
    help = "Give free coins: grant_coins 1000 --all  |  grant_coins 1000 --user sahil"

    def add_arguments(self, parser):
        parser.add_argument("amount", type=int)
        parser.add_argument("--user", help="username to credit")
        parser.add_argument("--all", action="store_true", help="credit every account")
        parser.add_argument("--label", default="Coins from Vibra")

    def handle(self, *args, amount, user, all, label, **kwargs):
        if amount <= 0:
            raise CommandError("amount must be positive")
        users = get_user_model().objects.all()
        if user:
            users = users.filter(username=user)
        elif not all:
            raise CommandError("pass --user USERNAME or --all")
        rows = [Transaction(user=u, type=Transaction.TYPE_BONUS, amount=amount, label=label) for u in users]
        Transaction.objects.bulk_create(rows)
        self.stdout.write(f"credited {amount} coins to {len(rows)} account(s)")
