"""
Seed / refresh the five standard job-position role groups for every active company.
Safe to re-run — existing groups are updated in place (user assignments preserved).
"""
from django.core.management.base import BaseCommand

from pos.models import Company, PermissionGroup

# ---------------------------------------------------------------------------
# Job-position permission sets — ordered from most to least privileged
# ---------------------------------------------------------------------------

SUPER_ADMIN_PERMISSIONS = ["*"]

ADMINISTRATOR_PERMISSIONS = [
    # General
    "dashboard.view",
    # POS Terminal
    "pos.view", "pos.sell", "pos.hold",
    # Shifts & cash
    "shift.open", "shift.close", "shift.view", "cash.manage",
    # Sales Control
    "sales.view", "sales.control",
    "sale.void", "sale.reprint", "sale.refund", "sale.refund.approve",
    "sale.discount", "sales.payments", "sales.discounts", "sales.customer", "sales.audit",
    # Inventory
    "inventory.view", "inventory.products", "inventory.categories", "inventory.suppliers",
    "inventory.adjust", "inventory.variance", "inventory.warehouses", "inventory.reports",
    "purchase_order.create", "purchase_order.receive", "purchase_order.cancel",
    "stocktake.manage",
    # Reports
    "reports.view", "reports.export",
    # Administration (no super-admin / no backup / no security)
    "admin.company.view", "admin.branches", "admin.users", "admin.roles",
    "admin.settings", "admin.audit", "admin.notifications",
    "admin.financial", "admin.pricing",
    "admin.reports", "admin.scheduled_reports",
    # General
    "alerts.view", "settings.view",
]

BRANCH_MANAGER_PERMISSIONS = [
    # General
    "dashboard.view",
    # POS Terminal
    "pos.view", "pos.sell", "pos.hold",
    # Shifts & cash
    "shift.open", "shift.close", "shift.view", "cash.manage",
    # Sales Control
    "sales.view", "sales.control",
    "sale.void", "sale.reprint", "sale.refund", "sale.refund.approve",
    "sale.discount", "sales.payments", "sales.discounts", "sales.customer", "sales.audit",
    # Inventory (view & ordering — no edit of products/categories)
    "inventory.view", "inventory.reports", "inventory.variance",
    "purchase_order.create", "purchase_order.receive", "purchase_order.cancel",
    "stocktake.manage",
    # Reports
    "reports.view", "reports.export",
    # Administration (audit only — no user/branch/settings management)
    "admin.audit",
    # General
    "alerts.view",
]

SUPERVISOR_PERMISSIONS = [
    # General
    "dashboard.view",
    # POS Terminal
    "pos.view", "pos.sell", "pos.hold",
    # Shifts & cash
    "shift.open", "shift.close", "shift.view", "cash.manage",
    # Sales Control (approve/monitor — no customer reports)
    "sales.view", "sales.control",
    "sale.void", "sale.reprint", "sale.refund", "sale.refund.approve",
    "sale.discount", "sales.discounts",
    # General
    "alerts.view",
]

CASHIER_PERMISSIONS = [
    # POS Terminal only
    "pos.view", "pos.sell", "pos.hold",
    "shift.open", "shift.close", "shift.view",
    "sale.reprint",
    "sales.view",
]

DEFAULT_GROUPS = [
    {
        "name": "Super Admin",
        "description": "Full system access — all branches, settings, backups, security.",
        "permissions": SUPER_ADMIN_PERMISSIONS,
    },
    {
        "name": "Administrator",
        "description": "Manages the business: users, products, branches, reports, pricing.",
        "permissions": ADMINISTRATOR_PERMISSIONS,
    },
    {
        "name": "Branch Manager",
        "description": "Manages one branch: sales, inventory ordering, approve refunds/voids, reports.",
        "permissions": BRANCH_MANAGER_PERMISSIONS,
    },
    {
        "name": "Supervisor",
        "description": "Between cashier and manager: approve discounts/refunds/voids, monitor cashiers.",
        "permissions": SUPERVISOR_PERMISSIONS,
    },
    {
        "name": "Cashier",
        "description": "POS only: sell, hold orders, print receipts, open/close shift.",
        "permissions": CASHIER_PERMISSIONS,
    },
]


def seed_default_groups_for_company(company):
    """Upsert the five default groups for a company. Returns (created, updated) counts."""
    created = []
    updated = []
    for group_def in DEFAULT_GROUPS:
        obj, is_new = PermissionGroup.objects.get_or_create(
            company=company,
            name=group_def["name"],
            defaults={
                "description": group_def["description"],
                "permissions": group_def["permissions"],
            },
        )
        if is_new:
            created.append(group_def["name"])
        else:
            # Always refresh permissions and description on existing groups
            obj.description = group_def["description"]
            obj.permissions = group_def["permissions"]
            obj.save(update_fields=["description", "permissions", "updated_at"])
            updated.append(group_def["name"])
    return created, updated


class Command(BaseCommand):
    help = (
        "Seed/refresh the five job-position role groups "
        "(Super Admin, Administrator, Branch Manager, Supervisor, Cashier) "
        "for all active companies. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            type=int,
            help="Limit to a specific company ID",
        )

    def handle(self, *args, **options):
        company_id = options.get("company")
        qs = Company.objects.filter(is_active=True)
        if company_id:
            qs = qs.filter(id=company_id)

        total_created = total_updated = 0
        for company in qs:
            created, updated = seed_default_groups_for_company(company)
            total_created += len(created)
            total_updated += len(updated)
            parts = []
            if created:
                parts.append(f"created: {', '.join(created)}")
            if updated:
                parts.append(f"updated: {', '.join(updated)}")
            self.stdout.write(
                self.style.SUCCESS(f"  {company.name}: {' | '.join(parts) or 'nothing to do'}")
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone — {total_created} created, {total_updated} updated."
            )
        )
