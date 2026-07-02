import uuid

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SyncMixin(models.Model):
    """Abstract mixin that adds offline-sync fields to any model."""
    LOCAL_ONLY = "local_only"
    PENDING_UPLOAD = "pending_upload"
    SYNCED = "synced"
    SYNC_ERROR = "sync_error"
    SYNC_STATUS_CHOICES = [
        (LOCAL_ONLY, "Local Only"),
        (PENDING_UPLOAD, "Pending Upload"),
        (SYNCED, "Synced"),
        (SYNC_ERROR, "Sync Error"),
    ]

    external_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    sync_status = models.CharField(max_length=20, choices=SYNC_STATUS_CHOICES, default=LOCAL_ONLY, db_index=True)
    device_id = models.CharField(max_length=64, blank=True, db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
