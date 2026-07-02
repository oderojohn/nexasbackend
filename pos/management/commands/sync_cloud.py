"""
python manage.py sync_cloud

Pushes local-only sales to the cloud and pulls the full catalog.
Called by the Electron main process whenever internet is available.

First run (no last_synced_at): full download of all entity types including users,
so that cashiers can log in to the local POS immediately after the initial sync.
Subsequent runs: incremental pull using the saved `since` timestamp.

Credentials come from CompanySettings.cloud_config (written by the Connect flow)
or from CLOUD_API_URL / CLOUD_SYNC_TOKEN / BRANCH_ID environment variables.
"""
import json
import logging
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from pos.models import (
    Branch,
    Category,
    Company,
    CompanySettings,
    Customer,
    DiscountRule,
    InventoryStock,
    Product,
    Sale,
    UserProfile,
)

logger = logging.getLogger(__name__)

FULL_INCLUDE = "products,categories,customers,users,stock,discount_rules"


def _api(cloud_url, token, method, path, body=None, timeout=30):
    url = f"{cloud_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except URLError as exc:
        raise RuntimeError(f"Cloud request failed ({method} {path}): {exc.reason}") from exc


class Command(BaseCommand):
    help = "Push local sales to cloud and pull full catalog + user data."

    def add_arguments(self, parser):
        parser.add_argument("--cloud-url", default="", help="Cloud API base URL (overrides DB config)")
        parser.add_argument("--token",     default="", help="Bearer token for cloud auth")
        parser.add_argument("--full",  action="store_true", help="Force full pull (ignore last_synced_at)")

    def handle(self, *args, **options):
        cloud_url, token, cloud_branch_id, cloud_company_id, device_uuid, cs = (
            self._get_cloud_config(options["cloud_url"], options["token"])
        )

        if not cloud_url or not token:
            self.stdout.write(self.style.WARNING(
                "Cloud sync skipped — run the Connect flow in the POS terminal "
                "or set CLOUD_API_URL / CLOUD_SYNC_TOKEN in nexapos.env."
            ))
            return

        if not cloud_branch_id:
            self.stdout.write(self.style.WARNING(
                "Cloud sync skipped — cloud_branch_id not set. Re-run the Connect flow."
            ))
            return

        # In DESKTOP_MODE there is exactly one active branch.
        local_branch = Branch.objects.filter(is_active=True).first()
        if not local_branch:
            self.stdout.write(self.style.ERROR(
                "No local branch found. Complete the Connect flow "
                "(Administration → Branches → POS Devices → Connect) before syncing."
            ))
            return

        # Decide full vs incremental
        force_full = options["full"]
        cfg = (cs.cloud_config or {}) if cs else {}
        last_synced_at = None if force_full else cfg.get("last_synced_at")

        since_param = f"&since={last_synced_at}" if last_synced_at else ""
        url_path    = (
            f"/api/pos/sync/pull/?branch={cloud_branch_id}"
            f"&include={FULL_INCLUDE}{since_param}"
        )

        sync_type = "incremental" if last_synced_at else "full"
        self.stdout.write(f"[sync] Starting {sync_type} pull from cloud branch {cloud_branch_id}…")

        try:
            data = _api(cloud_url, token, "GET", url_path)
        except RuntimeError as exc:
            self.stdout.write(self.style.ERROR(f"Pull failed: {exc}"))
            return

        total  = 0
        total += self._apply_company_branch(data, local_branch)
        total += self._apply_users(data.get("users", []), local_branch)
        total += self._apply_categories(data.get("categories", []), local_branch)
        total += self._apply_products(data.get("products", []), local_branch)
        total += self._apply_customers(data.get("customers", []), local_branch)
        total += self._apply_stock(data.get("stock", []), local_branch)
        total += self._apply_discount_rules(data.get("discount_rules", []), local_branch)

        pushed = self._push_sales(cloud_url, token, cloud_company_id, device_uuid)

        # Save last_synced_at so the next run is incremental.
        if cs:
            cfg = cs.cloud_config or {}
            cfg["last_synced_at"] = timezone.now().isoformat()
            cs.cloud_config = cfg
            cs.save(update_fields=["cloud_config"])

        self.stdout.write(self.style.SUCCESS(
            f"Cloud sync complete — pulled {total} record(s), pushed {pushed} sale(s)."
        ))

    # ── Config ──────────────────────────────────────────────────────────────

    def _get_cloud_config(self, cli_url="", cli_token=""):
        cloud_url        = cli_url.strip()
        token            = cli_token.strip()
        cloud_branch_id  = os.getenv("BRANCH_ID", "").strip()
        cloud_company_id = ""
        device_uuid      = ""
        cs               = None

        for settings_obj in CompanySettings.objects.all():
            cfg      = settings_obj.cloud_config or {}
            db_url   = cfg.get("cloud_api_url",   "").strip()
            db_token = cfg.get("cloud_sync_token", "").strip()
            if db_url and db_token:
                cloud_url        = cloud_url or db_url
                token            = token     or db_token
                # "cloud_branch_id" is written by local_bootstrap; "branch_id" is legacy
                cloud_branch_id  = (
                    cloud_branch_id
                    or cfg.get("cloud_branch_id", "")
                    or cfg.get("branch_id", "")
                )
                cloud_company_id = cfg.get("cloud_company_id", "")
                device_uuid      = cfg.get("device_id", "")
                cs = settings_obj
                break

        if not cloud_url:
            cloud_url = getattr(settings, "CLOUD_API_URL", "").strip()
        if not token:
            token = getattr(settings, "CLOUD_SYNC_TOKEN", "").strip()
        if not cloud_branch_id:
            cloud_branch_id = os.getenv("BRANCH_ID", "").strip()

        return cloud_url, token, cloud_branch_id, cloud_company_id, device_uuid, cs

    # ── Apply pulled data ────────────────────────────────────────────────────

    def _apply_company_branch(self, data, local_branch):
        """Keep local company/branch names in sync with cloud master data."""
        count        = 0
        company_data = data.get("company") or {}
        branch_data  = data.get("branch")  or {}

        if company_data.get("name"):
            company = local_branch.company
            if company.name != company_data["name"]:
                company.name = company_data["name"]
                company.save(update_fields=["name"])
            count += 1

        if branch_data.get("name"):
            changed = []
            if local_branch.name != branch_data["name"]:
                local_branch.name = branch_data["name"]
                changed.append("name")
            if branch_data.get("code") and local_branch.code != branch_data["code"]:
                local_branch.code = branch_data["code"]
                changed.append("code")
            if changed:
                local_branch.save(update_fields=changed)
            count += 1

        return count

    def _apply_users(self, items, branch):
        """
        Create / update local Django User + UserProfile records.

        Users authenticate via PIN in the POS terminal; password login is
        intentionally disabled on the local instance (set_unusable_password).
        The `pin_hash` from the cloud is stored in UserProfile.pin and is
        sufficient for PIN-based terminal login.
        """
        User  = get_user_model()
        count = 0

        for item in items:
            pos_username = (item.get("pos_username") or item.get("username") or "").strip()
            if not pos_username:
                continue

            full_name  = (item.get("full_name") or "").strip()
            parts      = full_name.split(" ", 1)
            first_name = parts[0] if parts else ""
            last_name  = parts[1] if len(parts) > 1 else ""

            user, created = User.objects.get_or_create(
                username=pos_username,
                defaults={
                    "email":      item.get("email") or "",
                    "first_name": first_name,
                    "last_name":  last_name,
                    "is_active":  item.get("is_active", True),
                },
            )
            if not created:
                user.first_name = first_name
                user.last_name  = last_name
                user.email      = item.get("email") or user.email
                user.is_active  = item.get("is_active", True)
                user.save(update_fields=["first_name", "last_name", "email", "is_active"])

            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])

            # Resolve the user's home branch via branch_code (stable across systems).
            target_branch = branch
            bc = (item.get("branch_code") or "").strip()
            if bc:
                lb = Branch.objects.filter(code=bc, company=branch.company).first()
                if lb:
                    target_branch = lb

            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "company":               branch.company,
                    "branch":                target_branch,
                    "role":                  item.get("role") or "cashier",
                    "access_level":          int(item.get("access_level") or 1),
                    "is_active":             item.get("is_active", True),
                    "pos_username":          pos_username,
                    "pin":                   item.get("pin_hash") or "",
                    "custom_permissions":    item.get("custom_permissions") or {},
                    "use_custom_permissions": bool(item.get("use_custom_permissions", False)),
                },
            )
            count += 1

        return count

    def _apply_categories(self, items, branch):
        count = 0
        for item in items:
            ext_id = item.get("external_id")
            if not ext_id:
                continue
            Category.objects.update_or_create(
                external_id=ext_id,
                defaults={
                    "branch":      branch,
                    "name":        item["name"],
                    "is_active":   item.get("is_active", True),
                    "sync_status": Sale.SYNCED,
                },
            )
            count += 1
        return count

    def _apply_products(self, items, branch):
        count = 0
        for item in items:
            ext_id = item.get("external_id")
            if not ext_id:
                continue

            category = None
            cat_ref = item.get("category_external_id") or item.get("category")
            if cat_ref:
                category = Category.objects.filter(
                    external_id=cat_ref, branch=branch
                ).first()
                if not category:
                    try:
                        category = Category.objects.filter(
                            pk=int(cat_ref), branch=branch
                        ).first()
                    except (ValueError, TypeError):
                        pass

            Product.objects.update_or_create(
                external_id=ext_id,
                defaults={
                    "branch":          branch,
                    "name":            item["name"],
                    "sku":             item.get("sku") or "",
                    "retail_price":    item.get("retail_price") or 0,
                    "wholesale_price": item.get("wholesale_price") or 0,
                    "category":        category,
                    "is_active":       item.get("is_active", True),
                    "sync_status":     Sale.SYNCED,
                },
            )
            count += 1
        return count

    def _apply_customers(self, items, branch):
        count = 0
        for item in items:
            ext_id = item.get("external_id")
            if not ext_id:
                continue
            Customer.objects.update_or_create(
                external_id=ext_id,
                defaults={
                    "branch":      branch,
                    "name":        item["name"],
                    "phone":       item.get("phone") or "",
                    "email":       item.get("email") or "",
                    "is_active":   item.get("is_active", True),
                    "sync_status": Sale.SYNCED,
                },
            )
            count += 1
        return count

    def _apply_stock(self, items, branch):
        count = 0
        for item in items:
            ext_id = item.get("product_external_id")
            if not ext_id:
                continue
            product = Product.objects.filter(external_id=ext_id, branch=branch).first()
            if not product:
                continue
            InventoryStock.objects.update_or_create(
                product=product,
                branch=branch,
                defaults={"quantity": item.get("quantity") or 0},
            )
            count += 1
        return count

    def _apply_discount_rules(self, items, branch):
        count = 0
        for item in items:
            name = item.get("name")
            if not name:
                continue
            DiscountRule.objects.update_or_create(
                name=name,
                branch=branch,
                defaults={
                    "discount_type": item.get("discount_type") or "percentage",
                    "value":         item.get("value") or "0",
                    "target":        item.get("target") or "all",
                    "start_date":    item.get("start_date"),
                    "end_date":      item.get("end_date"),
                    "days_of_week":  item.get("days_of_week") or [],
                    "start_time":    item.get("start_time"),
                    "end_time":      item.get("end_time"),
                    "is_active":     item.get("is_active", True),
                },
            )
            count += 1
        return count

    # ── Push local sales ─────────────────────────────────────────────────────

    def _push_sales(self, cloud_url, token, cloud_company_id="", device_uuid=""):
        pending = (
            Sale.objects.filter(sync_status=Sale.LOCAL_ONLY)
            .select_related("branch", "register", "shift", "cashier", "customer")
            .prefetch_related("items", "items__product", "payments")
        )

        count = 0
        for sale in pending:
            payload = {
                "device_uuid": device_uuid or "desktop",
                "company_id":  int(cloud_company_id) if cloud_company_id else None,
                "sales":       [self._serialize_sale(sale)],
            }
            try:
                result = _api(cloud_url, token, "POST", "/api/pos/sync/push/", body=payload)
                if result.get("succeeded", 0) > 0:
                    sale.sync_status    = Sale.SYNCED
                    sale.last_synced_at = timezone.now()
                    sale.save(update_fields=["sync_status", "last_synced_at"])
                    count += 1
                else:
                    sale.sync_status = Sale.SYNC_ERROR
                    sale.save(update_fields=["sync_status"])
                    logger.warning("Cloud rejected sale %s: %s", sale.receipt_no, result)
            except RuntimeError as exc:
                logger.error("Push failed for %s: %s", sale.receipt_no, exc)

        return count

    def _serialize_sale(self, sale):
        cashier_pos_username = None
        if sale.cashier:
            profile = getattr(sale.cashier, "pos_profile", None)
            if profile:
                cashier_pos_username = profile.pos_username

        return {
            "receipt_no":  sale.receipt_no,
            "external_id": str(sale.external_id) if getattr(sale, "external_id", None) else None,
            # Stable cross-system identifiers (preferred by cloud sync_push resolver)
            "branch_code":          sale.branch.code if sale.branch else None,
            "register_code":        sale.register.code if sale.register else None,
            "shift_external_id":    str(sale.shift.external_id) if sale.shift and getattr(sale.shift, "external_id", None) else None,
            "cashier_pos_username": cashier_pos_username,
            "customer_external_id": str(sale.customer.external_id) if sale.customer and getattr(sale.customer, "external_id", None) else None,
            # Integer PK fallbacks (in case stable IDs are not found)
            "branch":   sale.branch_id,
            "register": sale.register_id,
            "shift":    sale.shift_id,
            "cashier":  sale.cashier_id,
            "customer": sale.customer_id,
            "mode":       sale.mode,
            "created_at": sale.created_at.isoformat(),
            "items": [
                {
                    "product_external_id": str(item.product.external_id) if item.product and getattr(item.product, "external_id", None) else None,
                    "product":             item.product_id,
                    "quantity":            str(item.quantity),
                    "discount_amount":     str(item.discount_amount),
                }
                for item in sale.items.all()
            ],
            "payments": [
                {
                    "method":    payment.method,
                    "amount":    str(payment.amount),
                    "reference": payment.reference or "",
                }
                for payment in sale.payments.all()
            ],
        }
