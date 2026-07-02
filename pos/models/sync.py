import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from ._base import TimeStampedModel
from .company import Branch, Company


class SyncQueue(models.Model):
    """Tracks offline mutations waiting to be uploaded to the server."""
    PENDING = "pending"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (UPLOADING, "Uploading"),
        (DONE, "Done"),
        (FAILED, "Failed"),
    ]

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ACTION_CHOICES = [(CREATE, "Create"), (UPDATE, "Update"), (DELETE, "Delete")]

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    model_name = models.CharField(max_length=80)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    error_message = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    device_id = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_tried_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"SyncQueue({self.model_name}.{self.action} device={self.device_id} status={self.status})"


class DeviceRegistration(TimeStampedModel):
    """Tracks each POS terminal registered to this cloud instance."""
    device_uuid = models.UUIDField(unique=True, null=True, blank=True, db_index=True)
    device_id = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    company = models.ForeignKey(
        Company, related_name="devices", null=True, blank=True, on_delete=models.SET_NULL
    )
    branch = models.ForeignKey(
        Branch, related_name="devices", null=True, blank=True, on_delete=models.SET_NULL
    )
    terminal_id = models.CharField(max_length=20, blank=True)
    machine_name = models.CharField(max_length=120, blank=True)
    os_info = models.CharField(max_length=120, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    device_secret = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.terminal_id or self.device_id} ({self.name})"


class PairingToken(TimeStampedModel):
    """
    Single-use token embedded in a Connection Package.
    Valid for 60 minutes; invalidated on first use.
    """
    token = models.CharField(max_length=64, unique=True, db_index=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="pairing_tokens")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="pairing_tokens")
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by_device_uuid = models.UUIDField(null=True, blank=True)
    package_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "used" if self.is_used else ("expired" if self.is_expired else "valid")
        return f"PairingToken({self.branch} {state})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired


class ReportSchedule(TimeStampedModel):
    """Per-branch scheduled email reports (daily close, weekly, monthly summaries)."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    REPORT_TYPE_CHOICES = [
        (DAILY, "Daily"),
        (WEEKLY, "Weekly"),
        (MONTHLY, "Monthly"),
    ]
    DAY_OF_WEEK_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    branch = models.ForeignKey(
        Branch, related_name="report_schedules", on_delete=models.CASCADE
    )
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES, default=DAILY)
    is_enabled = models.BooleanField(default=False)
    send_hour = models.IntegerField(default=23)
    send_minute = models.IntegerField(default=0)
    send_day_of_week = models.IntegerField(null=True, blank=True, choices=DAY_OF_WEEK_CHOICES)
    send_day_of_month = models.IntegerField(null=True, blank=True)
    recipients = models.JSONField(default=list)
    include_gross_profit = models.BooleanField(default=True)
    include_cashier_breakdown = models.BooleanField(default=True)
    include_payment_methods = models.BooleanField(default=True)
    include_top_products = models.BooleanField(default=False)
    include_returns = models.BooleanField(default=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_report_schedules",
    )

    class Meta:
        unique_together = [("branch", "report_type")]
        ordering = ["branch", "report_type"]

    def __str__(self):
        return f"{self.branch} — {self.get_report_type_display()} report"
