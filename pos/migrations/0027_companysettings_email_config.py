from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0026_reportschedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="email_config",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
