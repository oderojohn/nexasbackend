import re

from django.db import migrations, models


def backfill_company_codes(apps, schema_editor):
    Company = apps.get_model("pos", "Company")
    used = set()
    for company in Company.objects.all().order_by("id"):
        base = re.sub(r"[^A-Z0-9]", "", (company.name or "").upper())[:10] or "CO"
        candidate = base
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{base}{suffix}"
        used.add(candidate)
        company.code = candidate
        company.save(update_fields=["code"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0033_pairingtoken_device_secret"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="code",
            field=models.CharField(max_length=20, default="", blank=True),
        ),
        migrations.RunPython(backfill_company_codes, noop),
        migrations.AlterField(
            model_name="company",
            name="code",
            field=models.CharField(max_length=20, unique=True),
        ),
    ]
