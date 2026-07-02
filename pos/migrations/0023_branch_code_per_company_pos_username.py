from django.db import migrations, models


def backfill_pos_username(apps, schema_editor):
    """Set pos_username = user.username for all existing profiles."""
    UserProfile = apps.get_model("pos", "UserProfile")
    User = apps.get_model("auth", "User")
    user_map = {u.id: u.username for u in User.objects.all()}
    profiles = list(UserProfile.objects.filter(pos_username=""))
    for profile in profiles:
        profile.pos_username = user_map.get(profile.user_id, "")
    if profiles:
        UserProfile.objects.bulk_update(profiles, ["pos_username"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0022_userprofile_pin_max_length"),
    ]

    operations = [
        # 1. Drop the global unique constraint on Branch.code
        migrations.AlterField(
            model_name="branch",
            name="code",
            field=models.CharField(max_length=20),
        ),
        # 2. Add per-company unique constraint for Branch.code
        migrations.AddConstraint(
            model_name="branch",
            constraint=models.UniqueConstraint(
                fields=["company", "code"],
                name="unique_branch_code_per_company",
            ),
        ),
        # 3. Add pos_username field to UserProfile
        migrations.AddField(
            model_name="userprofile",
            name="pos_username",
            field=models.CharField(blank=True, max_length=150, default=""),
            preserve_default=False,
        ),
        # 4. Backfill pos_username from existing Django usernames
        migrations.RunPython(backfill_pos_username, migrations.RunPython.noop),
        # 5. Add per-company unique constraint for pos_username (only when non-empty)
        migrations.AddConstraint(
            model_name="userprofile",
            constraint=models.UniqueConstraint(
                fields=["company", "pos_username"],
                condition=models.Q(pos_username__gt=""),
                name="unique_pos_username_per_company",
            ),
        ),
    ]
