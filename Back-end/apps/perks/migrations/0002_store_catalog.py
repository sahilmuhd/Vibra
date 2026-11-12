"""Seed the store: avatar frames and mounts (7-day rentals). Adds only
missing items, never changes prices of existing ones."""
from django.db import migrations

ITEMS = [
    # kind, key, name, price, sort
    ("frame", "neon", "Neon Pulse", 500, 1),
    ("frame", "rose", "Rose Garden", 1500, 2),
    ("frame", "ice", "Frost Crystal", 3000, 3),
    ("frame", "gold", "Royal Gold", 8000, 4),
    ("frame", "flame", "Inferno", 15000, 5),
    ("frame", "galaxy", "Galaxy", 30000, 6),
    ("mount", "bike", "Street Bike", 3000, 1),
    ("mount", "car", "Supercar", 8000, 2),
    ("mount", "rocket", "Rocket", 15000, 3),
    ("mount", "unicorn", "Unicorn", 25000, 4),
    ("mount", "ufo", "UFO", 40000, 5),
    ("mount", "dragon", "Dragon", 80000, 6),
]


def seed(apps, schema_editor):
    StoreItem = apps.get_model("perks", "StoreItem")
    have = set(StoreItem.objects.values_list("kind", "key"))
    StoreItem.objects.bulk_create([
        StoreItem(kind=k, key=key, name=name, price=price, sort=sort, days=7)
        for k, key, name, price, sort in ITEMS if (k, key) not in have
    ])


class Migration(migrations.Migration):

    dependencies = [
        ("perks", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
