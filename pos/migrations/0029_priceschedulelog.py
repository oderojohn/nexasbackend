from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0028_discountrulelog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PriceScheduleLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('performed_at', models.DateTimeField(auto_now_add=True)),
                ('action', models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('deleted', 'Deleted'), ('applied', 'Applied')], max_length=20)),
                ('product_name', models.CharField(max_length=240)),
                ('schedule_snapshot', models.JSONField(default=dict)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_schedule_logs', to='pos.branch')),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='price_schedule_logs', to=settings.AUTH_USER_MODEL)),
                ('schedule', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='logs', to='pos.priceschedule')),
            ],
            options={
                'ordering': ['-performed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='priceschedulelog',
            index=models.Index(fields=['branch', '-performed_at'], name='pos_pricesch_branch__idx'),
        ),
    ]
