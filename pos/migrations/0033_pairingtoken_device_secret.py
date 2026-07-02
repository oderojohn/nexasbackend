import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0032_device_registration_upgrade"),
    ]

    operations = [
        migrations.AddField(
            model_name="deviceregistration",
            name="device_secret",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.CreateModel(
            name="PairingToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("is_used", models.BooleanField(db_index=True, default=False)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("used_by_device_uuid", models.UUIDField(blank=True, null=True)),
                ("package_snapshot", models.JSONField(blank=True, default=dict)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pairing_tokens", to="pos.company")),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pairing_tokens", to="pos.branch")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
