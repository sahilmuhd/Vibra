from datetime import datetime, timedelta, timezone

from django.db import migrations

IST = timezone(timedelta(hours=5, minutes=30))

EVENTS = [
    {
        "key": "festival-of-lights", "name": "Festival of Lights", "style": "lights",
        "tagline": "Light up Vibra — limited diya & rangoli frames and a glowing lantern ride",
        "starts_at": datetime(2026, 11, 1, 0, 0, tzinfo=IST), "ends_at": datetime(2026, 12, 1, 0, 0, tzinfo=IST),
        "items": [("frame", "diya", "Golden Diya", 2500, 1), ("frame", "rangoli", "Rangoli Bloom", 4500, 2),
                  ("mount", "lantern", "Sky Lantern", 9000, 3)],
    },
    {
        "key": "winter-wonderland", "name": "Winter Wonderland", "style": "winter",
        "tagline": "Snowflake frames and a reindeer sleigh — only this winter",
        "starts_at": datetime(2026, 12, 15, 0, 0, tzinfo=IST), "ends_at": datetime(2027, 1, 8, 0, 0, tzinfo=IST),
        "items": [("frame", "snowflake", "Snowflake Crown", 3000, 1), ("mount", "reindeer", "Reindeer Sleigh", 9000, 2)],
    },
]


def seed(apps, schema_editor):
    SeasonEvent = apps.get_model("perks", "SeasonEvent")
    StoreItem = apps.get_model("perks", "StoreItem")
    for e in EVENTS:
        ev, _ = SeasonEvent.objects.update_or_create(key=e["key"], defaults={
            k: e[k] for k in ("name", "style", "tagline", "starts_at", "ends_at")})
        for kind, key, name, price, sort in e["items"]:
            StoreItem.objects.update_or_create(kind=kind, key=key, defaults={
                "name": name, "price": price, "days": 14, "sort": 50 + sort, "is_active": True, "event": ev})


def unseed(apps, schema_editor):
    apps.get_model("perks", "StoreItem").objects.filter(key__in=["diya", "rangoli", "lantern", "snowflake", "reindeer"]).delete()
    apps.get_model("perks", "SeasonEvent").objects.filter(key__in=[e["key"] for e in EVENTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("perks", "0004_seasonevent_storeitem_event")]
    operations = [migrations.RunPython(seed, unseed)]
