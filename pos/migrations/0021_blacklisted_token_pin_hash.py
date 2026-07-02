import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.contrib.auth.hashers import make_password, is_password_usable
from django.db import migrations, models


def hash_existing_pins(apps, schema_editor):
    UserProfile = apps.get_model("pos", "UserProfile")
    profiles = UserProfile.objects.exclude(pin="").only("id", "pin")
    to_update = []
    for profile in profiles:
        if profile.pin and not is_password_usable(profile.pin):
            # Already hashed (shouldn't happen, but be safe)
            continue
        if profile.pin and not profile.pin.startswith(("pbkdf2_", "bcrypt", "argon2")):
            profile.pin = make_password(profile.pin)
            to_update.append(profile)
    if to_update:
        UserProfile.objects.bulk_update(to_update, ["pin"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0020_sync_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BlacklistedToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blacklisted_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("blacklisted_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="blacklistedtoken",
            index=models.Index(fields=["expires_at"], name="pos_blackli_expires_idx"),
        ),
        migrations.RunPython(hash_existing_pins, migrations.RunPython.noop),
    ]
