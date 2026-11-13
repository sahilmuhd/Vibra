from django.db import migrations, models

THEMES = [
    ("rain", "Midnight Rain", 800, 1),
    ("beach", "Sunset Beach", 1500, 2),
    ("neoncity", "Neon City", 3000, 3),
    ("sakura", "Sakura Garden", 5000, 4),
    ("galaxy", "Deep Galaxy", 10000, 5),
]


def seed(apps, schema_editor):
    StoreItem = apps.get_model("perks", "StoreItem")
    for key, name, price, sort in THEMES:
        StoreItem.objects.update_or_create(kind="theme", key=key, defaults={
            "name": name, "price": price, "days": 30, "sort": sort, "is_active": True})


def unseed(apps, schema_editor):
    apps.get_model("perks", "StoreItem").objects.filter(kind="theme").delete()


class Migration(migrations.Migration):
    dependencies = [("perks", "0002_store_catalog")]
    operations = [
        migrations.AlterField(
            model_name="storeitem", name="kind",
            field=models.CharField(choices=[("frame", "Avatar frame"), ("mount", "Mount"), ("theme", "Room theme")],
                                   max_length=10),
        ),
        migrations.RunPython(seed, unseed),
    ]
