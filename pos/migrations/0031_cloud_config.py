from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0030_permission_groups'),
    ]

    operations = [
        migrations.AddField(
            model_name='companysettings',
            name='cloud_config',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
