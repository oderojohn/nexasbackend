"""
Management command: send_scheduled_reports

Run this command from a cron job (e.g. every 15 minutes) to deliver
scheduled email reports that are due. Example crontab:

  */15 * * * * cd /path/to/backend && python manage.py send_scheduled_reports

Or run once manually to test a specific branch/type:
  python manage.py send_scheduled_reports --branch 1 --type daily
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from pos.models import ReportSchedule
from pos.views_reports import send_report


class Command(BaseCommand):
    help = "Send scheduled email reports that are due based on configured schedule times."

    def add_arguments(self, parser):
        parser.add_argument("--branch", type=int, help="Only process this branch ID")
        parser.add_argument(
            "--type",
            choices=["daily", "weekly", "monthly"],
            help="Only process this report type",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Send even if the report was already sent today/this week/this month",
        )

    def handle(self, *args, **options):
        now = timezone.localtime()
        today = now.date()
        current_hour = now.hour
        current_minute = now.minute
        current_dow = now.weekday()  # 0=Monday
        current_dom = today.day

        qs = ReportSchedule.objects.filter(is_enabled=True).select_related(
            "branch", "branch__company"
        )
        if options.get("branch"):
            qs = qs.filter(branch_id=options["branch"])
        if options.get("type"):
            qs = qs.filter(report_type=options["type"])

        sent = 0
        skipped = 0
        errors = 0

        for schedule in qs:
            try:
                if not self._is_due(schedule, now, today, current_hour, current_minute,
                                    current_dow, current_dom, options.get("force")):
                    skipped += 1
                    continue

                if not schedule.recipients:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipping {schedule} — no recipients configured"
                        )
                    )
                    skipped += 1
                    continue

                self.stdout.write(f"  Sending {schedule}...")
                send_report(schedule)
                sent += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Sent to {schedule.recipients}"))

            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"  ✗ Error sending {schedule}: {exc}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {sent} sent, {skipped} skipped, {errors} errors."
            )
        )

    def _is_due(self, schedule, now, today, hour, minute, dow, dom, force):
        # Check time window (within the scheduled hour:minute window, ±14 minutes)
        scheduled_minutes = schedule.send_hour * 60 + schedule.send_minute
        current_minutes = hour * 60 + minute
        in_window = abs(current_minutes - scheduled_minutes) <= 14

        if not in_window and not force:
            return False

        last = schedule.last_sent_at
        if last:
            last_local = timezone.localtime(last)

        if schedule.report_type == ReportSchedule.DAILY:
            if force:
                return True
            return last is None or timezone.localtime(last).date() < today

        elif schedule.report_type == ReportSchedule.WEEKLY:
            target_dow = schedule.send_day_of_week if schedule.send_day_of_week is not None else 0
            if dow != target_dow and not force:
                return False
            if force:
                return True
            if last is None:
                return True
            # Sent more than 6 days ago
            return (now - last).days >= 6

        else:  # MONTHLY
            target_dom = schedule.send_day_of_month if schedule.send_day_of_month else 1
            if dom != target_dom and not force:
                return False
            if force:
                return True
            if last is None:
                return True
            last_local = timezone.localtime(last)
            return not (last_local.year == now.year and last_local.month == now.month)
