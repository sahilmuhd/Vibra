from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rooms", "0007_gift_catalog")]
    operations = [
        migrations.AddField(model_name="room", name="theme", field=models.CharField(blank=True, max_length=32)),
        migrations.AddField(model_name="room", name="password", field=models.CharField(blank=True, max_length=128)),
        migrations.AddField(model_name="room", name="announcement", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="room", name="welcome_message", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="room", name="slow_mode", field=models.PositiveSmallIntegerField(default=0)),
    ]
