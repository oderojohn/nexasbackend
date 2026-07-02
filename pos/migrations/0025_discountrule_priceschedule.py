from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0024_product_branch_active_index'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DiscountRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=120)),
                ('discount_type', models.CharField(choices=[('percent', 'Percentage (%)'), ('fixed', 'Fixed Amount (KES)')], default='percent', max_length=10)),
                ('value', models.DecimalField(decimal_places=2, max_digits=10)),
                ('target', models.CharField(choices=[('all', 'All Products'), ('category', 'Category'), ('product', 'Specific Product')], default='all', max_length=10)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('days_of_week', models.JSONField(blank=True, default=list)),
                ('start_time', models.TimeField(blank=True, null=True)),
                ('end_time', models.TimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='discount_rules', to='pos.branch')),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='discount_rules', to='pos.category')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_discount_rules', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='discount_rules', to='pos.product')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='PriceSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('new_retail_price', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('new_wholesale_price', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('effective_at', models.DateTimeField()),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('is_applied', models.BooleanField(db_index=True, default=False)),
                ('note', models.CharField(blank=True, max_length=240)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_schedules', to='pos.branch')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_price_schedules', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_schedules', to='pos.product')),
            ],
            options={'ordering': ['effective_at']},
        ),
    ]
