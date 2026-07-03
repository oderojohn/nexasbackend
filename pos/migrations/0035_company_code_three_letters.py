import random
import re
import string

import django.core.validators
from django.db import migrations, models


def shorten_company_codes(apps, schema_editor):
    Company = apps.get_model("pos", "Company")
    used = set()
    for company in Company.objects.all().order_by("id"):
        letters = re.sub(r"[^A-Z]", "", (company.name or "").upper())
        candidates = [letters[start:start + 3] for start in range(0, max(len(letters) - 2, 0))]
        candidate = next((c for c in candidates if len(c) == 3 and c not in used), None)
        if not candidate:
            while True:
                candidate = "".join(random.choices(string.ascii_uppercase, k=3))
                if candidate not in used:
                    break
        used.add(candidate)
        company.code = candidate
        company.save(update_fields=["code"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0034_company_code"),
    ]

    operations = [
        migrations.RunPython(shorten_company_codes, noop),
        migrations.AlterField(
            model_name="company",
            name="code",
            field=models.CharField(
                max_length=3,
                unique=True,
                validators=[django.core.validators.RegexValidator("^[A-Z]{3}$", "Company code must be exactly 3 letters.")],
            ),
        ),
    ]
