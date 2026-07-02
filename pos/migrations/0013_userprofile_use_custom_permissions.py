from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0012_userprofile_custom_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="use_custom_permissions",
            field=models.BooleanField(default=False),
        ),
    ]
