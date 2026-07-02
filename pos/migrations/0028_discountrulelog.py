from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0027_companysettings_email_config'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DiscountRuleLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('performed_at', models.DateTimeField(auto_now_add=True)),
                ('action', models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('deleted', 'Deleted'), ('activated', 'Activated'), ('deactivated', 'Deactivated')], max_length=20)),
                ('rule_name', models.CharField(max_length=120)),
                ('rule_snapshot', models.JSONField(default=dict)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='discount_rule_logs', to='pos.branch')),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='discount_rule_logs', to=settings.AUTH_USER_MODEL)),
                ('rule', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='logs', to='pos.discountrule')),
            ],
            options={
                'ordering': ['-performed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='discountrulelog',
            index=models.Index(fields=['branch', '-performed_at'], name='pos_discoun_branch__idx'),
        ),
    ]
