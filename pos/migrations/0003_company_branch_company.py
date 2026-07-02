# Generated migration for Company model

from django.db import migrations, models
import django.db.models.deletion


def create_default_company(apps, schema_editor):
    Company = apps.get_model("pos", "Company")
    Branch = apps.get_model("pos", "Branch")
    company, _ = Company.objects.get_or_create(
        name="Demo Company",
        defaults={"currency": "KES", "vat_rate": 16, "is_active": True},
    )
    Branch.objects.filter(company__isnull=True).update(company=company)


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0002_auditlog_purchaseorder_purchaseorderitem_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=160)),
                ("currency", models.CharField(default="KES", max_length=10)),
                ("vat_rate", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name_plural": "Companies",
            },
        ),
        migrations.AddField(
            model_name="branch",
            name="company",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.CASCADE, related_name="branches", to="pos.company"),
        ),
        migrations.RunPython(create_default_company, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="branch",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="branches", to="pos.company"),
        ),
    ]
