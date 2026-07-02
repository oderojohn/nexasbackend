from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0011_company_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="custom_permissions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
