"""
GET /api/pos/system-health/

Returns real-time system metrics: application uptime, database response,
disk space, CPU/RAM (requires psutil), POS terminal heartbeats, and sync state.
All metrics degrade gracefully — if a sub-query fails the field is null rather
than crashing the whole response.
"""
import shutil
import time

from django.db import connection
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import DeviceRegistration, SyncQueue, UserProfile
from .permissions import get_pos_profile

APP_VERSION = "2.5.0"
_PROCESS_START = time.monotonic()  # seconds since this worker process started


def _require_admin(user):
    if user.is_superuser:
        return
    profile = get_pos_profile(user)
    if profile and profile.access_level in (
        UserProfile.SUPER_ADMIN,
        UserProfile.COMPANY_ADMIN,
        UserProfile.BRANCH_ADMIN,
    ):
        return
    raise PermissionDenied("Admin access required to view system health.")


@api_view(["GET"])
def system_health(request):
    _require_admin(request.user)
    now = timezone.now()

    # ── Application uptime ────────────────────────────────────────────────────
    uptime_s = time.monotonic() - _PROCESS_START
    uptime_days = int(uptime_s // 86400)
    uptime_hours = int((uptime_s % 86400) // 3600)

    # ── Database ping ─────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        db_response_ms = round((time.monotonic() - t0) * 1000)
        db_status = "healthy"
    except Exception:
        db_response_ms = None
        db_status = "error"

    # PostgreSQL-only metrics (skipped silently on SQLite)
    db_size_gb = db_connections = db_connections_max = None
    try:
        db_name = connection.settings_dict.get("NAME", "")
        with connection.cursor() as cur:
            cur.execute("SELECT pg_database_size(%s)", [db_name])
            db_size_gb = round(cur.fetchone()[0] / (1024 ** 3), 2)
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
            )
            db_connections = cur.fetchone()[0]
            cur.execute("SHOW max_connections")
            db_connections_max = int(cur.fetchone()[0])
    except Exception:
        pass

    # ── Disk storage ──────────────────────────────────────────────────────────
    storage_free_gb = storage_total_gb = storage_used_pct = None
    try:
        usage = shutil.disk_usage("/")
        storage_free_gb = round(usage.free / (1024 ** 3), 1)
        storage_total_gb = round(usage.total / (1024 ** 3), 1)
        storage_used_pct = round(usage.used / usage.total * 100, 1)
    except Exception:
        pass

    # ── CPU / RAM (requires psutil) ───────────────────────────────────────────
    cpu_percent = ram_percent = None
    try:
        import psutil  # noqa: PLC0415 – optional dep
        cpu_percent = round(psutil.cpu_percent(interval=0.2))
        ram_percent = round(psutil.virtual_memory().percent)
    except (ImportError, Exception):
        pass

    # ── POS terminal heartbeats ───────────────────────────────────────────────
    online_cutoff = now - timedelta(minutes=5)
    stale_cutoff = now - timedelta(minutes=30)

    all_devices = list(
        DeviceRegistration.objects.filter(is_active=True).select_related("branch")
    )
    online = [d for d in all_devices if d.last_seen_at and d.last_seen_at >= online_cutoff]
    offline = [d for d in all_devices if not d.last_seen_at or d.last_seen_at < online_cutoff]

    terminal_warnings = []
    for d in offline:
        if d.last_seen_at and d.last_seen_at >= now - timedelta(hours=24):
            mins = int((now - d.last_seen_at).total_seconds() / 60)
            label = f"Terminal '{d.name}' has not synchronized for {mins} minute{'s' if mins != 1 else ''}."
            terminal_warnings.append(label)

    # ── Offline sync queue ────────────────────────────────────────────────────
    pending_sync = SyncQueue.objects.filter(status="pending").count()
    last_device = (
        DeviceRegistration.objects.filter(last_seen_at__isnull=False)
        .order_by("-last_seen_at")
        .first()
    )
    last_sync_at = last_device.last_seen_at if last_device else None
    last_sync_mins = (
        int((now - last_sync_at).total_seconds() / 60) if last_sync_at else None
    )

    # ── Sync status breakdown ─────────────────────────────────────────────────
    status_counts = {
        row["status"]: row["count"]
        for row in SyncQueue.objects.values("status").annotate(count=Count("id"))
    }
    sync_status_counts = {
        "pending":   status_counts.get("pending", 0),
        "uploading": status_counts.get("uploading", 0),
        "done":      status_counts.get("done", 0),
        "failed":    status_counts.get("failed", 0),
    }

    # Last 20 failed entries with enough detail to diagnose
    recent_failed = list(
        SyncQueue.objects.filter(status="failed")
        .order_by("-last_tried_at")[:20]
        .values(
            "id", "external_id", "model_name", "action",
            "error_message", "attempts", "device_id",
            "created_at", "last_tried_at",
        )
    )
    # Serialize UUIDs/datetimes to strings
    for entry in recent_failed:
        entry["external_id"] = str(entry["external_id"])
        if entry["created_at"]:
            entry["created_at"] = entry["created_at"].isoformat()
        if entry["last_tried_at"]:
            entry["last_tried_at"] = entry["last_tried_at"].isoformat()

    # Per-device breakdown: name, status, last_seen, pending/done/failed counts
    device_map = {d.device_id: d for d in all_devices}
    # Devices that have sync queue entries but may not be in DeviceRegistration
    device_counts_qs = (
        SyncQueue.objects.filter(device_id__gt="")
        .values("device_id", "status")
        .annotate(count=Count("id"))
    )
    device_agg: dict = {}
    for row in device_counts_qs:
        did = row["device_id"]
        if did not in device_agg:
            dev = device_map.get(did)
            device_agg[did] = {
                "device_id": did,
                "name": dev.name if dev else did,
                "branch": dev.branch.name if dev and dev.branch else None,
                "last_seen_at": dev.last_seen_at.isoformat() if dev and dev.last_seen_at else None,
                "is_active": dev.is_active if dev else False,
                "pending": 0,
                "uploading": 0,
                "done": 0,
                "failed": 0,
            }
        device_agg[did][row["status"]] = row["count"]

    device_breakdown = sorted(
        device_agg.values(),
        key=lambda d: d["last_seen_at"] or "",
        reverse=True,
    )

    # Recent sync log: last 50 SyncQueue entries across all statuses
    recent_log = list(
        SyncQueue.objects.order_by("-created_at")[:50]
        .values(
            "id", "model_name", "action", "status",
            "device_id", "attempts", "error_message",
            "created_at", "last_tried_at",
        )
    )
    for entry in recent_log:
        if entry["created_at"]:
            entry["created_at"] = entry["created_at"].isoformat()
        if entry["last_tried_at"]:
            entry["last_tried_at"] = entry["last_tried_at"].isoformat()

    # ── Aggregate status ──────────────────────────────────────────────────────
    warnings = list(terminal_warnings)
    critical = []

    if db_status == "error":
        critical.append("Database connection failed.")
    if storage_free_gb is not None and storage_free_gb < 5:
        critical.append(f"Low disk space: only {storage_free_gb} GB remaining.")
    if cpu_percent is not None and cpu_percent > 90:
        warnings.append(f"High CPU usage: {cpu_percent}%.")
    if ram_percent is not None and ram_percent > 90:
        warnings.append(f"High RAM usage: {ram_percent}%.")

    overall = "critical" if critical else ("warning" if warnings else "healthy")

    return Response({
        "status": overall,
        "application": {
            "status": "running",
            "version": APP_VERSION,
            "uptime_days": uptime_days,
            "uptime_hours": uptime_hours,
        },
        "database": {
            "status": db_status,
            "response_ms": db_response_ms,
            "size_gb": db_size_gb,
            "connections_active": db_connections,
            "connections_max": db_connections_max,
        },
        "storage": {
            "free_gb": storage_free_gb,
            "total_gb": storage_total_gb,
            "used_percent": storage_used_pct,
        },
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
        "pos_terminals": {
            "online": len(online),
            "offline": len(offline),
            "total": len(all_devices),
            "warnings": terminal_warnings,
        },
        "sync": {
            "last_sync_at": last_sync_at,
            "last_sync_minutes_ago": last_sync_mins,
            "pending_count": pending_sync,
            "status_counts": sync_status_counts,
            "recent_failed": recent_failed,
            "device_breakdown": device_breakdown,
            "recent_log": recent_log,
        },
        "warnings": warnings,
        "critical_issues": critical,
    })
