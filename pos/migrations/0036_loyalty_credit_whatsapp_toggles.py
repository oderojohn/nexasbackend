from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0035_company_code_three_letters"),
    ]

    operations = [
        migrations.AddField(
            model_name="branch",
            name="loyalty_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="loyalty_points_rate",
            field=models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("100.00")),
        ),
        migrations.AddField(
            model_name="branch",
            name="credit_sale_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="branch",
            name="whatsapp_sms_receipt_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="customer",
            name="credit_balance",
            field=models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00")),
        ),
        migrations.AddField(
            model_name="customer",
            name="loyalty_points",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
