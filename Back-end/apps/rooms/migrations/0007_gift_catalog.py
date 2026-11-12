"""Seed the gift catalog. Only adds gifts whose name is not there yet, so it is
safe on databases that already have some gifts (and never edits prices).

animation_key tells the client how to play it:
  ""          small: flies to the recipient
  "burst"     medium: fly + sparkle burst
  anything else is a full-screen effect of that name (rocket, fireworks, ...).
"""
from django.db import migrations

GIFTS = [
    # name, emoji, cost, animation_key
    ("Rose", "🌹", 10, ""),
    ("Heart", "❤️", 20, ""),
    ("Kiss", "💋", 30, ""),
    ("Teddy", "🧸", 50, ""),
    ("Lollipop", "🍭", 66, ""),
    ("Bouquet", "💐", 99, "burst"),
    ("Love Letter", "💌", 199, "burst"),
    ("Diamond Ring", "💍", 299, "burst"),
    ("Rocket", "🚀", 1000, "rocket"),
    ("Fireworks", "🎆", 1314, "fireworks"),
    ("Crown", "👑", 2000, "crown"),
    ("Supercar", "🏎️", 3000, "car"),
    ("Castle", "🏰", 5000, "castle"),
    ("Dragon", "🐉", 9999, "dragon"),
]


def seed(apps, schema_editor):
    Gift = apps.get_model("rooms", "Gift")
    existing = set(Gift.objects.values_list("name", flat=True))
    Gift.objects.bulk_create([
        Gift(name=name, emoji=emoji, cost=cost, animation_key=key)
        for name, emoji, cost, key in GIFTS if name not in existing
    ])


def unseed(apps, schema_editor):
    Gift = apps.get_model("rooms", "Gift")
    Gift.objects.filter(name__in=[g[0] for g in GIFTS], giftevent__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rooms", "0006_alter_room_seat_count"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
