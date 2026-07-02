import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0031_cloud_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="deviceregistration",
            name="device_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="devices",
                to="pos.company",
            ),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="terminal_id",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="machine_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="os_info",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="app_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="registered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deviceregistration",
            name="deactivated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
