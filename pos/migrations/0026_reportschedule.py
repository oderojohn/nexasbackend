from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0025_discountrule_priceschedule"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("report_type", models.CharField(
                    choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
                    default="daily", max_length=20,
                )),
                ("is_enabled", models.BooleanField(default=False)),
                ("send_hour", models.IntegerField(default=23)),
                ("send_minute", models.IntegerField(default=0)),
                ("send_day_of_week", models.IntegerField(
                    blank=True, null=True,
                    choices=[(0,"Monday"),(1,"Tuesday"),(2,"Wednesday"),(3,"Thursday"),(4,"Friday"),(5,"Saturday"),(6,"Sunday")],
                )),
                ("send_day_of_month", models.IntegerField(blank=True, null=True)),
                ("recipients", models.JSONField(default=list)),
                ("include_gross_profit", models.BooleanField(default=True)),
                ("include_cashier_breakdown", models.BooleanField(default=True)),
                ("include_payment_methods", models.BooleanField(default=True)),
                ("include_top_products", models.BooleanField(default=False)),
                ("include_returns", models.BooleanField(default=True)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("branch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="report_schedules",
                    to="pos.branch",
                )),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_report_schedules",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["branch", "report_type"]},
        ),
        migrations.AddConstraint(
            model_name="reportschedule",
            constraint=models.UniqueConstraint(
                fields=["branch", "report_type"],
                name="unique_report_schedule_per_branch_type",
            ),
        ),
    ]
