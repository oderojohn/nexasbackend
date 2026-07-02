"""
Migration 0020: Add offline-sync fields (SyncMixin) to key transactional models
and introduce SyncQueue + DeviceRegistration models.

Three-step pattern for external_id (works on both SQLite and PostgreSQL):
  1. Add as nullable (no unique constraint) — safe for existing rows
  2. RunPython: populate each row with a distinct UUID
  3. AlterField: make non-nullable and add unique constraint
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


# ── Models that get SyncMixin fields ─────────────────────────────────────────
_SYNC_MODELS = [
    "category",
    "customer",
    "heldorder",
    "product",
    "purchaseorder",
    "sale",
    "shift",
    "stockmovement",
    "cashtransaction",
    "supplier",
]

_SYNC_STATUS_CHOICES = [
    ("local_only", "Local Only"),
    ("pending_upload", "Pending Upload"),
    ("synced", "Synced"),
    ("sync_error", "Sync Error"),
]


def populate_external_ids(apps, schema_editor):
    """Assign a unique UUID to every existing row on all SyncMixin models."""
    model_names = [
        "Category", "Customer", "HeldOrder", "Product",
        "PurchaseOrder", "Sale", "Shift", "StockMovement",
        "CashTransaction", "Supplier",
    ]
    for model_name in model_names:
        Model = apps.get_model("pos", model_name)
        for obj in Model.objects.all():
            obj.external_id = uuid.uuid4()
            obj.save(update_fields=["external_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0019_branch_mpesa_manual_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── PHASE 1: Add external_id as nullable (no unique yet) ──────────
        *[
            migrations.AddField(
                model_name=m,
                name="external_id",
                field=models.UUIDField(null=True, blank=True, editable=False),
                preserve_default=False,
            )
            for m in _SYNC_MODELS
        ],

        # ── PHASE 2: Populate unique UUIDs on all existing rows ───────────
        migrations.RunPython(populate_external_ids, migrations.RunPython.noop),

        # ── PHASE 3: Add unique + not-null constraint on external_id ──────
        *[
            migrations.AlterField(
                model_name=m,
                name="external_id",
                field=models.UUIDField(
                    default=uuid.uuid4, editable=False, unique=True, db_index=True
                ),
            )
            for m in _SYNC_MODELS
        ],

        # ── sync_status, device_id, last_synced_at on all SyncMixin models ─
        *[
            migrations.AddField(
                model_name=m,
                name="sync_status",
                field=models.CharField(
                    choices=_SYNC_STATUS_CHOICES,
                    db_index=True, default="local_only", max_length=20,
                ),
            )
            for m in _SYNC_MODELS
        ],
        *[
            migrations.AddField(
                model_name=m,
                name="device_id",
                field=models.CharField(blank=True, db_index=True, max_length=64),
            )
            for m in _SYNC_MODELS
        ],
        *[
            migrations.AddField(
                model_name=m,
                name="last_synced_at",
                field=models.DateTimeField(blank=True, null=True),
            )
            for m in _SYNC_MODELS
        ],

        # ── New model: SyncQueue ──────────────────────────────────────────
        migrations.CreateModel(
            name="SyncQueue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ("model_name", models.CharField(max_length=80)),
                ("action", models.CharField(
                    choices=[("create", "Create"), ("update", "Update"), ("delete", "Delete")],
                    max_length=20,
                )),
                ("payload", models.JSONField(default=dict)),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("uploading", "Uploading"), ("done", "Done"), ("failed", "Failed")],
                    db_index=True, default="pending", max_length=20,
                )),
                ("error_message", models.TextField(blank=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("device_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_tried_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["created_at"]},
        ),

        # ── New model: DeviceRegistration ─────────────────────────────────
        migrations.CreateModel(
            name="DeviceRegistration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("device_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("branch", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="devices", to="pos.branch",
                )),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["-last_seen_at"]},
        ),
    ]
