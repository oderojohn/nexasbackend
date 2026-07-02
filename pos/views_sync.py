"""
Offline sync + device registration endpoints.

POST /api/pos/sync/device-register/ — register / re-register a POS terminal (requires admin auth)
PATCH /api/pos/sync/device-register/ — deactivate / rename a device (requires admin auth)
GET  /api/pos/sync/devices/          — list company devices (requires admin auth)
POST /api/pos/sync/device-checkin/   — legacy heartbeat (no auth required)
POST /api/pos/sync/push/             — upload locally-created sales from a device
GET  /api/pos/sync/pull/             — download catalog / user changes since a timestamp
"""
import hashlib
import hmac
import logging
import secrets
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import (
    Branch,
    Category,
    Company,
    CompanySettings,
    Customer,
    DeviceRegistration,
    DiscountRule,
    InventoryStock,
    PairingToken,
    Product,
    Register,
    Sale,
    Shift,
    SyncQueue,
    UserProfile,
)
from .permissions import get_pos_profile
from .serializers import (
    CategorySerializer,
    CustomerSerializer,
    ProductSerializer,
    SaleSerializer,
)
from .services import checkout_sale
from .views_helpers import is_company_admin, is_super_admin

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=dt_timezone.utc)
        except (ValueError, TypeError):
            pass
    return None


def _resolve_company_for_user(user):
    profile = get_pos_profile(user)
    if not profile:
        return None
    if profile.company:
        return profile.company
    if profile.branch:
        return profile.branch.company
    return None


def _resolve_branch(branch_id=None, branch_code=None, company=None):
    """Resolve a Branch by integer PK or by (code, company) — whichever is provided."""
    if branch_code and company:
        b = Branch.objects.filter(code=branch_code, company=company, is_active=True).first()
        if b:
            return b
    if branch_id:
        try:
            return Branch.objects.get(pk=int(branch_id), is_active=True)
        except (Branch.DoesNotExist, ValueError, TypeError):
            pass
    return None


# ── Device registration ───────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def device_register(request):
    """
    Register or re-register a POS terminal.

    Only company admins or super-admins may call this endpoint.

    Body:
      {
        "device_uuid":    "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "terminal_name":  "Main Register",
        "machine_name":   "DESKTOP-ABC123",
        "os_info":        "Windows 10 Pro 19045",
        "app_version":    "1.0.0",
        "branch_id":      3          // cloud Branch.pk
      }

    Returns full company / branch context + assigned terminal_id.
    """
    if not (is_company_admin(request.user) or is_super_admin(request.user)):
        return Response(
            {"detail": "Only company administrators can register POS devices."},
            status=status.HTTP_403_FORBIDDEN,
        )

    company = _resolve_company_for_user(request.user)
    if not company:
        return Response(
            {"detail": "Your account is not associated with a company."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    device_uuid_str = (request.data.get("device_uuid") or "").strip()
    if not device_uuid_str:
        return Response({"detail": "device_uuid is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        device_uuid = uuid_lib.UUID(device_uuid_str)
    except ValueError:
        return Response({"detail": "device_uuid must be a valid UUID."}, status=status.HTTP_400_BAD_REQUEST)

    terminal_name = (request.data.get("terminal_name") or "").strip()
    machine_name = (request.data.get("machine_name") or "").strip()
    os_info = (request.data.get("os_info") or "").strip()
    app_version = (request.data.get("app_version") or "").strip()
    branch_id = request.data.get("branch_id")

    branch = None
    if branch_id:
        try:
            branch = Branch.objects.get(pk=int(branch_id), company=company, is_active=True)
        except (Branch.DoesNotExist, ValueError, TypeError):
            return Response(
                {"detail": f"Branch {branch_id!r} not found in your company."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    existing = DeviceRegistration.objects.filter(device_uuid=device_uuid).first()
    if existing:
        terminal_id = existing.terminal_id
        registered_at = existing.registered_at or timezone.now()
    else:
        count = DeviceRegistration.objects.filter(company=company).count()
        terminal_id = f"T-{count + 1:03d}"
        registered_at = timezone.now()

    display_name = terminal_name or machine_name or f"Terminal {terminal_id}"

    reg, created = DeviceRegistration.objects.update_or_create(
        device_uuid=device_uuid,
        defaults={
            "device_id": str(device_uuid),
            "name": display_name,
            "company": company,
            "branch": branch,
            "terminal_id": terminal_id,
            "machine_name": machine_name,
            "os_info": os_info,
            "app_version": app_version,
            "registered_at": registered_at,
            "last_seen_at": timezone.now(),
            "is_active": True,
            "deactivated_at": None,
        },
    )

    available_branches = list(
        Branch.objects.filter(company=company, is_active=True)
        .order_by("name")
        .values("id", "name", "code", "location")
    )

    logger.info(
        "[device-register] %s device_uuid=%s terminal=%s branch=%s company=%s",
        "created" if created else "updated",
        str(device_uuid),
        terminal_id,
        branch.code if branch else None,
        company.name,
    )

    return Response({
        "device_uuid": str(reg.device_uuid),
        "terminal_id": reg.terminal_id,
        "company_id": company.id,
        "company_name": company.name,
        "branch_id": branch.id if branch else None,
        "branch_name": branch.name if branch else None,
        "branch_code": branch.code if branch else None,
        "available_branches": available_branches,
        "created": created,
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def devices_list(request):
    """List all registered devices for the authenticated user's company."""
    if not (is_company_admin(request.user) or is_super_admin(request.user)):
        return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

    company = _resolve_company_for_user(request.user)
    qs = DeviceRegistration.objects.filter(company=company).select_related("branch")

    branch_filter = request.query_params.get("branch")
    if branch_filter:
        try:
            qs = qs.filter(branch_id=int(branch_filter))
        except (ValueError, TypeError):
            pass

    return Response([
        {
            "device_uuid": str(d.device_uuid) if d.device_uuid else None,
            "terminal_id": d.terminal_id,
            "name": d.name,
            "branch": (
                {"id": d.branch_id, "name": d.branch.name, "code": d.branch.code}
                if d.branch else None
            ),
            "machine_name": d.machine_name,
            "os_info": d.os_info,
            "app_version": d.app_version,
            "is_active": d.is_active,
            "deactivated_at": d.deactivated_at,
            "last_seen_at": d.last_seen_at,
            "registered_at": d.registered_at,
        }
        for d in qs
    ])


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def device_manage(request, device_uuid):
    """Rename or deactivate a registered device."""
    if not (is_company_admin(request.user) or is_super_admin(request.user)):
        return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

    company = _resolve_company_for_user(request.user)
    try:
        device = DeviceRegistration.objects.get(device_uuid=device_uuid, company=company)
    except DeviceRegistration.DoesNotExist:
        return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

    if "name" in request.data:
        device.name = (request.data["name"] or "").strip() or device.name
    if "is_active" in request.data:
        if not bool(request.data["is_active"]):
            device.is_active = False
            device.deactivated_at = timezone.now()
        else:
            device.is_active = True
            device.deactivated_at = None
    device.save()
    return Response({"detail": "Device updated."})


# ── Legacy device check-in ─────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def device_checkin(request):
    """Legacy heartbeat — register or refresh a device's last_seen_at timestamp."""
    device_id = (request.data.get("device_id") or "").strip()
    name = (request.data.get("name") or "").strip()
    branch_id = request.data.get("branch")

    if not device_id:
        raise ValidationError({"device_id": "device_id is required."})
    if len(device_id) > 64:
        raise ValidationError({"device_id": "device_id max length is 64 characters."})

    branch = None
    if branch_id:
        try:
            branch = Branch.objects.get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            raise ValidationError({"branch": "Branch not found or inactive."})

    reg, created = DeviceRegistration.objects.update_or_create(
        device_id=device_id,
        defaults={
            "name": name or device_id,
            "branch": branch,
            "last_seen_at": timezone.now(),
            "is_active": True,
        },
    )
    return Response({
        "device_id": reg.device_id,
        "name": reg.name,
        "branch": reg.branch_id,
        "last_seen_at": reg.last_seen_at,
        "created": created,
    })


# ── Offline-sale push ─────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def sync_push(request):
    """
    Accept a batch of offline sales from a POS device.

    Resolves FK references by stable identifiers (UUID / code) first,
    falling back to integer PK so legacy clients still work.

    Body:
      {
        "device_uuid":  "...",          // preferred
        "device_id":    "...",          // fallback legacy
        "company_id":   1,              // cloud Company.pk
        "sales": [
          {
            "receipt_no":            "BR01-...",
            "external_id":           "uuid",
            "branch_code":           "NKR",    // preferred
            "register_code":         "R01",    // preferred
            "shift_external_id":     "uuid",   // preferred
            "cashier_pos_username":  "jane",   // preferred
            "customer_external_id":  "uuid",   // preferred
            // legacy fallbacks:
            "branch":   1, "register": 2, "shift": 3, "cashier": 4, "customer": null,
            "mode":     "retail",
            "created_at": "2025-06-01T10:30:00Z",
            "items": [
              {
                "product_external_id": "uuid",  // preferred
                "product":  5,                   // fallback
                "quantity": 2, "discount_amount": "0.00"
              }
            ],
            "payments": [{"method": "cash", "amount": "100.00", "reference": ""}]
          }
        ]
      }
    """
    device_uuid_str = (request.data.get("device_uuid") or "").strip()
    device_id = (request.data.get("device_id") or device_uuid_str).strip()
    company_id = request.data.get("company_id")
    sales_payload = request.data.get("sales") or []

    if not device_id:
        raise ValidationError({"device_id": "device_id or device_uuid is required."})
    if not isinstance(sales_payload, list):
        raise ValidationError({"sales": "Expected a list of sale objects."})

    # Resolve company for FK scoping
    company = None
    device = None
    if device_uuid_str:
        try:
            device = DeviceRegistration.objects.select_related("company", "branch").get(
                device_uuid=uuid_lib.UUID(device_uuid_str)
            )
            company = device.company
        except (DeviceRegistration.DoesNotExist, ValueError):
            pass

    if not company and company_id:
        company = Company.objects.filter(pk=company_id).first()

    # Update device heartbeat
    if device:
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_seen_at"])
    else:
        DeviceRegistration.objects.filter(device_id=device_id).update(last_seen_at=timezone.now())

    from django.contrib.auth import get_user_model
    User = get_user_model()

    results = []
    for raw_sale in sales_payload:
        receipt_no = (raw_sale.get("receipt_no") or "").strip()
        if not receipt_no:
            results.append({"receipt_no": None, "success": False, "error": "receipt_no is required."})
            continue

        if Sale.objects.filter(receipt_no=receipt_no).exists():
            results.append({"receipt_no": receipt_no, "success": True, "duplicate": True})
            continue

        sq, _ = SyncQueue.objects.get_or_create(
            external_id=raw_sale.get("external_id") or receipt_no,
            defaults={
                "model_name": "Sale",
                "action": SyncQueue.CREATE,
                "payload": raw_sale,
                "device_id": device_id,
                "status": SyncQueue.UPLOADING,
            },
        )
        sq.status = SyncQueue.UPLOADING
        sq.attempts += 1
        sq.last_tried_at = timezone.now()
        sq.save(update_fields=["status", "attempts", "last_tried_at"])

        try:
            # --- Branch ---
            branch = _resolve_branch(
                branch_id=raw_sale.get("branch"),
                branch_code=raw_sale.get("branch_code"),
                company=company,
            )
            if not branch:
                raise ValueError(f"Branch not found: code={raw_sale.get('branch_code')!r} id={raw_sale.get('branch')!r}")

            # --- Register ---
            register = None
            register_code = raw_sale.get("register_code")
            if register_code:
                register = Register.objects.filter(code=register_code, branch=branch).first()
            if not register and raw_sale.get("register"):
                try:
                    register = Register.objects.get(pk=raw_sale["register"])
                except Register.DoesNotExist:
                    pass
            if not register:
                raise ValueError(f"Register not found: code={register_code!r} id={raw_sale.get('register')!r}")

            # --- Shift ---
            shift = None
            shift_ext = raw_sale.get("shift_external_id")
            if shift_ext:
                shift = Shift.objects.filter(external_id=shift_ext).first()
            if not shift and raw_sale.get("shift"):
                try:
                    shift = Shift.objects.get(pk=raw_sale["shift"])
                except Shift.DoesNotExist:
                    pass
            if not shift:
                raise ValueError(f"Shift not found: external_id={shift_ext!r} pk={raw_sale.get('shift')!r}")

            # --- Cashier ---
            cashier = None
            cashier_username = raw_sale.get("cashier_pos_username")
            if cashier_username and company:
                profile = UserProfile.objects.select_related("user").filter(
                    company=company, pos_username=cashier_username, is_active=True
                ).first()
                if profile:
                    cashier = profile.user
            if not cashier and raw_sale.get("cashier"):
                try:
                    cashier = User.objects.get(pk=raw_sale["cashier"])
                except User.DoesNotExist:
                    pass
            if not cashier:
                raise ValueError(f"Cashier not found: pos_username={cashier_username!r} pk={raw_sale.get('cashier')!r}")

            # --- Customer ---
            customer = None
            cust_ext = raw_sale.get("customer_external_id")
            if cust_ext:
                customer = Customer.objects.filter(external_id=cust_ext).first()
            if not customer and raw_sale.get("customer"):
                try:
                    customer = Customer.objects.get(pk=raw_sale["customer"])
                except Customer.DoesNotExist:
                    pass

            # --- Items ---
            items = []
            for item in raw_sale.get("items", []):
                product = None
                prod_ext = item.get("product_external_id")
                if prod_ext:
                    product = Product.objects.filter(external_id=prod_ext).first()
                if not product and item.get("product"):
                    try:
                        product = Product.objects.get(pk=item["product"])
                    except Product.DoesNotExist:
                        pass
                if not product:
                    raise ValueError(f"Product not found: external_id={prod_ext!r} pk={item.get('product')!r}")
                items.append({
                    "product": product,
                    "quantity": item["quantity"],
                    "discount_amount": item.get("discount_amount", "0.00"),
                })

            payments = [
                {"method": p["method"], "amount": p["amount"], "reference": p.get("reference", "")}
                for p in raw_sale.get("payments", [])
            ]

            sale = checkout_sale(
                cashier=cashier,
                branch=branch,
                register=register,
                shift=shift,
                customer=customer,
                mode=raw_sale.get("mode", Sale.RETAIL),
                items=items,
                payments=payments,
                device_id=device_id,
                receipt_no=receipt_no,
            )
            sq.status = SyncQueue.DONE
            sq.save(update_fields=["status"])
            results.append({"receipt_no": receipt_no, "success": True, "sale_id": sale.id})

        except Exception as exc:
            error_msg = str(exc)
            sq.status = SyncQueue.FAILED
            sq.error_message = error_msg[:2000]
            sq.save(update_fields=["status", "error_message"])
            logger.warning("Sync push failed for receipt %s: %s", receipt_no, error_msg)
            results.append({"receipt_no": receipt_no, "success": False, "error": error_msg})

    succeeded = sum(1 for r in results if r.get("success"))
    return Response({
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    })


# ── Catalog + user pull ───────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def sync_pull(request):
    """
    Return data changed since a given timestamp.

    Accepts branch by:
      ?branch=<pk>                           (legacy)
      ?branch_code=<code>&company_id=<pk>    (preferred — stable across systems)

    Query params:
      since     — ISO-8601 datetime; omit for full pull
      include   — comma-separated: products, categories, customers, users,
                  discount_rules  (default: products,categories,customers)
    """
    # Resolve branch
    branch_code = (request.query_params.get("branch_code") or "").strip()
    company_id = request.query_params.get("company_id")
    branch_pk = request.query_params.get("branch")

    branch = None
    if branch_code and company_id:
        try:
            branch = Branch.objects.get(code=branch_code, company_id=int(company_id), is_active=True)
        except (Branch.DoesNotExist, ValueError, TypeError):
            pass

    if not branch and branch_pk:
        try:
            branch = Branch.objects.get(pk=int(branch_pk), is_active=True)
        except (Branch.DoesNotExist, ValueError, TypeError):
            pass

    if not branch:
        raise ValidationError({"branch": "Valid branch is required (use branch_code+company_id or branch pk)."})

    since_raw = request.query_params.get("since")
    since = _parse_dt(since_raw)

    include_raw = request.query_params.get("include", "products,categories,customers")
    include = {s.strip() for s in include_raw.split(",")}

    company = branch.company
    payload = {
        "branch_id":  branch.id,
        "branch_code": branch.code,
        "company_id": branch.company_id,
        "pulled_at":  timezone.now(),
        # Bootstrap metadata — the local Electron POS uses these to create
        # its first Company and Branch records during the initial sync.
        "company": {"id": company.id, "name": company.name},
        "branch":  {"id": branch.id,  "code": branch.code, "name": branch.name},
    }

    if "categories" in include:
        qs = Category.objects.filter(branch=branch, is_active=True)
        if since:
            qs = qs.filter(updated_at__gt=since)
        payload["categories"] = CategorySerializer(qs, many=True).data

    if "products" in include:
        qs = Product.objects.filter(branch=branch, is_active=True).select_related("category")
        if since:
            qs = qs.filter(updated_at__gt=since)
        payload["products"] = ProductSerializer(qs, many=True).data

    if "customers" in include:
        qs = Customer.objects.filter(branch=branch, is_active=True)
        if since:
            qs = qs.filter(updated_at__gt=since)
        payload["customers"] = CustomerSerializer(qs, many=True).data

    if "users" in include:
        qs = UserProfile.objects.filter(
            company=branch.company, is_active=True
        ).select_related("user")
        if since:
            qs = qs.filter(updated_at__gt=since)
        payload["users"] = [
            {
                "external_id": None,
                "username": p.user.username,
                "pos_username": p.pos_username,
                "full_name": p.user.get_full_name(),
                "email": p.user.email,
                "role": p.role,
                "access_level": p.access_level,
                "branch_code": p.branch.code if p.branch else None,
                "is_active": p.is_active,
                "custom_permissions": p.custom_permissions,
                "use_custom_permissions": p.use_custom_permissions,
                "pin_hash": p.pin or "",
            }
            for p in qs
        ]

    if "discount_rules" in include:
        qs = DiscountRule.objects.filter(branch=branch, is_active=True)
        if since:
            qs = qs.filter(updated_at__gt=since)
        payload["discount_rules"] = [
            {
                "external_id": None,
                "name": r.name,
                "discount_type": r.discount_type,
                "value": str(r.value),
                "target": r.target,
                "start_date": str(r.start_date) if r.start_date else None,
                "end_date": str(r.end_date) if r.end_date else None,
                "days_of_week": r.days_of_week,
                "start_time": str(r.start_time) if r.start_time else None,
                "end_time": str(r.end_time) if r.end_time else None,
                "is_active": r.is_active,
            }
            for r in qs
        ]

    if "stock" in include:
        qs = InventoryStock.objects.filter(branch=branch).select_related("product")
        payload["stock"] = [
            {
                "product_id": s.product_id,
                "product_external_id": str(s.product.external_id) if s.product.external_id else None,
                "quantity": s.quantity,
            }
            for s in qs
        ]

    return Response(payload)


# ── Connection Package ────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_pairing_token(request):
    """
    Generate a single-use connection package for a branch POS device.

    Only company admins or super-admins may call this endpoint.

    Body:
      { "branch_id": 3 }

    Returns a full connection package JSON that can be pasted into the
    Electron POS to authenticate and register the device.
    """
    if not (is_company_admin(request.user) or is_super_admin(request.user)):
        return Response(
            {"detail": "Only company administrators can generate connection packages."},
            status=status.HTTP_403_FORBIDDEN,
        )

    company = _resolve_company_for_user(request.user)
    if not company:
        return Response({"detail": "Your account is not associated with a company."}, status=400)

    branch_id = request.data.get("branch_id")
    if not branch_id:
        return Response({"detail": "branch_id is required."}, status=400)

    try:
        branch = Branch.objects.get(pk=int(branch_id), company=company, is_active=True)
    except (Branch.DoesNotExist, ValueError, TypeError):
        return Response({"detail": f"Branch {branch_id!r} not found in your company."}, status=404)

    # Invalidate any existing unused tokens for this branch (clean up stale ones)
    PairingToken.objects.filter(
        branch=branch,
        is_used=False,
        expires_at__gt=timezone.now(),
    ).update(expires_at=timezone.now())

    # Generate a cryptographically secure token
    token = secrets.token_hex(32)  # 64 hex chars
    expires_at = timezone.now() + timedelta(minutes=60)

    # Build canonical cloud URLs from the request context
    cloud_url = request.build_absolute_uri("/").rstrip("/")
    api_url = f"{cloud_url}/api/pos"

    # HMAC signature so the POS can verify the package wasn't tampered with
    from django.conf import settings as _settings
    sig_key = _settings.SECRET_KEY.encode("utf-8")[:32]
    sig_msg = f"{company.id}:{branch.id}:{token}:{expires_at.isoformat()}".encode("utf-8")
    signature = hmac.new(sig_key, sig_msg, hashlib.sha256).hexdigest()[:32]

    package = {
        "packageVersion": "1.0",
        "companyId": company.id,
        "companyName": company.name,
        "branchId": branch.id,
        "branchName": branch.name,
        "branchCode": branch.code,
        "cloudUrl": cloud_url,
        "apiUrl": api_url,
        "pairingToken": token,
        "expiresAt": expires_at.isoformat(),
        "apiVersion": "1",
        "currency": company.currency or "KES",
        "timezone": "Africa/Nairobi",
        "signature": signature,
    }

    PairingToken.objects.create(
        token=token,
        company=company,
        branch=branch,
        expires_at=expires_at,
        package_snapshot=package,
    )

    logger.info(
        "[generate-pairing-token] company=%s branch=%s expires=%s",
        company.name,
        branch.code,
        expires_at.isoformat(),
    )

    return Response(package)


@api_view(["POST"])
@permission_classes([AllowAny])
def validate_pairing_token(request):
    """
    Validate a connection package token without consuming it.

    Called by the Electron POS before the user clicks 'Connect'.
    Returns a check-by-check breakdown so the UI can display results.

    Body:
      { "pairingToken": "..." }
    """
    token = (request.data.get("pairingToken") or "").strip()
    if not token:
        return Response({"valid": False, "detail": "pairingToken is required."}, status=400)

    try:
        pairing = PairingToken.objects.select_related("company", "branch").get(token=token)
    except PairingToken.DoesNotExist:
        return Response({
            "valid": False,
            "checks": {
                "cloud_reachable": True,
                "api_version_compatible": True,
                "token_valid": False,
                "token_not_expired": False,
                "company_exists": False,
                "branch_exists": False,
                "license_active": False,
            },
        })

    company_ok = pairing.company is not None and pairing.company.is_active
    branch_ok = pairing.branch is not None and pairing.branch.is_active

    checks = {
        "cloud_reachable": True,
        "api_version_compatible": True,
        "token_valid": not pairing.is_used,
        "token_not_expired": not pairing.is_expired,
        "company_exists": company_ok,
        "branch_exists": branch_ok,
        "license_active": True,
    }

    return Response({
        "valid": all(checks.values()),
        "checks": checks,
        "companyName": pairing.company.name if pairing.company else None,
        "branchName": pairing.branch.name if pairing.branch else None,
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def pair_device(request):
    """
    Consume a pairing token and register the Electron POS device.

    This is the 'Connect' step. After success, the device immediately
    starts the initial full synchronisation using the returned syncToken.

    Body:
      {
        "pairingToken":   "...",
        "deviceUuid":     "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "machineName":    "DESKTOP-ABC123",
        "osInfo":         "Windows 10 Pro 19045",
        "appVersion":     "1.0.0",
        "localDbVersion": "0"
      }

    Returns:
      {
        "registrationStatus": "SUCCESS",
        "deviceId":     "...",
        "terminalId":   "T-001",
        "deviceSecret": "...",
        "syncToken":    "...",
        "companyId":    1,
        "companyName":  "...",
        "branchId":     3,
        "branchName":   "...",
        "branchCode":   "NKR"
      }
    """
    token = (request.data.get("pairingToken") or "").strip()
    device_uuid_str = (request.data.get("deviceUuid") or "").strip()
    machine_name = (request.data.get("machineName") or "").strip()
    os_info = (request.data.get("osInfo") or "").strip()
    app_version = (request.data.get("appVersion") or "").strip()

    if not token:
        return Response(
            {"detail": "pairingToken is required.", "registrationStatus": "FAILED"},
            status=400,
        )
    if not device_uuid_str:
        return Response(
            {"detail": "deviceUuid is required.", "registrationStatus": "FAILED"},
            status=400,
        )
    try:
        device_uuid = uuid_lib.UUID(device_uuid_str)
    except ValueError:
        return Response(
            {"detail": "deviceUuid must be a valid UUID.", "registrationStatus": "FAILED"},
            status=400,
        )

    try:
        pairing = PairingToken.objects.select_related("company", "branch").get(token=token)
    except PairingToken.DoesNotExist:
        return Response(
            {"detail": "Invalid pairing token.", "registrationStatus": "FAILED"},
            status=400,
        )

    if pairing.is_used:
        return Response(
            {"detail": "This pairing token has already been used.", "registrationStatus": "FAILED"},
            status=400,
        )
    if pairing.is_expired:
        return Response(
            {"detail": "This pairing token has expired. Generate a new connection package.", "registrationStatus": "FAILED"},
            status=400,
        )

    company = pairing.company
    branch = pairing.branch

    # Assign terminal ID
    existing = DeviceRegistration.objects.filter(device_uuid=device_uuid).first()
    if existing:
        terminal_id = existing.terminal_id
        registered_at = existing.registered_at or timezone.now()
    else:
        count = DeviceRegistration.objects.filter(company=company).count()
        terminal_id = f"T-{count + 1:03d}"
        registered_at = timezone.now()

    # Generate a fresh device secret (used to authenticate future sync requests)
    device_secret = secrets.token_hex(32)
    display_name = machine_name or f"Terminal {terminal_id}"

    reg, created = DeviceRegistration.objects.update_or_create(
        device_uuid=device_uuid,
        defaults={
            "device_id": str(device_uuid),
            "name": display_name,
            "company": company,
            "branch": branch,
            "terminal_id": terminal_id,
            "machine_name": machine_name,
            "os_info": os_info,
            "app_version": app_version,
            "registered_at": registered_at,
            "last_seen_at": timezone.now(),
            "is_active": True,
            "deactivated_at": None,
            "device_secret": device_secret,
        },
    )

    # Consume the pairing token — single use only
    pairing.is_used = True
    pairing.used_at = timezone.now()
    pairing.used_by_device_uuid = device_uuid
    pairing.save(update_fields=["is_used", "used_at", "used_by_device_uuid"])

    logger.info(
        "[pair-device] %s device_uuid=%s terminal=%s branch=%s company=%s",
        "created" if created else "re-registered",
        str(device_uuid),
        terminal_id,
        branch.code,
        company.name,
    )

    return Response(
        {
            "registrationStatus": "SUCCESS",
            "deviceId": str(device_uuid),
            "terminalId": terminal_id,
            "deviceSecret": device_secret,
            "syncToken": device_secret,
            "companyId": company.id,
            "companyName": company.name,
            "branchId": branch.id,
            "branchName": branch.name,
            "branchCode": branch.code,
            "created": created,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


# ── Local bootstrap (DESKTOP_MODE only) ──────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def local_bootstrap(request):
    """
    Bootstrap a fresh local (DESKTOP_MODE) installation from the connection package.

    Creates the local Company, Branch, and CompanySettings records so that
    the subsequent sync_cloud run has something to sync into.  Safe to call
    multiple times (idempotent).

    Only reachable when DESKTOP_MODE=True; the cloud backend returns 403.

    Body (from pair_device response + connection package):
      {
        "companyId":   <cloud company pk>,
        "companyName": "Acme Ltd",
        "branchId":    <cloud branch pk>,
        "branchName":  "Nairobi Branch",
        "branchCode":  "NKR",
        "syncToken":   "<device_secret>",
        "deviceId":    "<uuid>",
        "terminalId":  "T-001",
        "cloudUrl":    "https://cloud.example.com",
        "apiUrl":      "https://cloud.example.com/api/pos"
      }
    """
    from django.conf import settings as _settings
    if not getattr(_settings, "DESKTOP_MODE", False):
        return Response(
            {"detail": "local-bootstrap is only available in desktop (offline) mode."},
            status=status.HTTP_403_FORBIDDEN,
        )

    data        = request.data
    company_id  = data.get("companyId")
    company_name = (data.get("companyName") or "").strip()
    branch_id   = data.get("branchId")
    branch_name  = (data.get("branchName") or "").strip()
    branch_code  = (data.get("branchCode") or "BR001").strip()
    sync_token   = (data.get("syncToken")  or "").strip()
    device_id    = (data.get("deviceId")   or "").strip()
    terminal_id  = (data.get("terminalId") or "").strip()
    cloud_url    = (data.get("cloudUrl")   or "").strip()
    api_url      = (data.get("apiUrl")     or "").strip()

    if not company_name:
        return Response({"detail": "companyName is required."}, status=400)
    if not branch_name:
        return Response({"detail": "branchName is required."}, status=400)
    if not sync_token:
        return Response({"detail": "syncToken is required."}, status=400)

    # In DESKTOP_MODE there is at most one company.
    company_qs = Company.objects.all()
    if company_qs.exists():
        company = company_qs.first()
        if company.name != company_name:
            company.name = company_name
            company.save(update_fields=["name"])
    else:
        company = Company.objects.create(name=company_name, code=Company.generate_code(company_name))

    # Find or create branch by code (code is stable across cloud and local).
    branch_qs = Branch.objects.filter(company=company, code=branch_code)
    if branch_qs.exists():
        branch = branch_qs.first()
        changed = []
        if branch.name != branch_name:
            branch.name = branch_name
            changed.append("name")
        if not branch.is_active:
            branch.is_active = True
            changed.append("is_active")
        if changed:
            branch.save(update_fields=changed)
    else:
        branch = Branch.objects.create(
            company=company,
            name=branch_name,
            code=branch_code,
            is_active=True,
        )

    # Persist cloud credentials in CompanySettings.cloud_config.
    cs, _ = CompanySettings.objects.get_or_create(company=company)
    cfg = cs.cloud_config or {}
    cfg.update({
        "cloud_company_id": str(company_id) if company_id else "",
        "cloud_branch_id":  str(branch_id)  if branch_id  else "",
        "cloud_api_url":    api_url or cloud_url,
        "cloud_sync_token": sync_token,
        "branch_id":        str(branch_id) if branch_id else "",
        "device_id":        device_id,
        "terminal_id":      terminal_id,
    })
    cs.cloud_config = cfg
    cs.save(update_fields=["cloud_config"])

    logger.info(
        "[local-bootstrap] company=%s branch=%s code=%s cloud_branch=%s",
        company.name, branch.name, branch.code, branch_id,
    )

    return Response({
        "status":          "OK",
        "local_company_id": company.id,
        "local_branch_id":  branch.id,
        "branch_code":      branch.code,
    })
