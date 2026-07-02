# Generated migration for user access levels

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0006_make_userprofile_branch_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='access_level',
            field=models.CharField(
                choices=[
                    ('super_admin', 'Super Admin'),
                    ('company_admin', 'Company Admin'),
                    ('branch_admin', 'Branch Admin'),
                    ('branch_staff', 'Branch Staff'),
                ],
                default='branch_staff',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='staff_profiles',
                to='pos.company',
            ),
        ),
    ]
