"""Give existing users the levels their past gifts have earned."""
import math

from django.db import migrations
from django.db.models import F, Sum


def level_for(xp):
    return min(99, math.isqrt(max(0, int(xp)) // 100) + 1)


def backfill(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    GiftEvent = apps.get_model("rooms", "GiftEvent")
    value = Sum(F("gift__cost") * F("combo"))
    spent = dict(GiftEvent.objects.values("sender").annotate(v=value).values_list("sender", "v"))
    received = dict(GiftEvent.objects.values("recipient").annotate(v=value).values_list("recipient", "v"))
    for p in Profile.objects.filter(user_id__in=set(spent) | set(received)):
        p.wealth_xp = spent.get(p.user_id, 0) or 0
        p.charm_xp = received.get(p.user_id, 0) or 0
        p.level = level_for(p.wealth_xp)
        p.save(update_fields=["wealth_xp", "charm_xp", "level"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_profile_charm_xp_profile_frame_key_and_more"),
        ("rooms", "0007_gift_catalog"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
