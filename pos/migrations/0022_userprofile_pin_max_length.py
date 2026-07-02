from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0021_blacklisted_token_pin_hash"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="pin",
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
