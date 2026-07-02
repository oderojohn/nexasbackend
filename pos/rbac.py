"""
Role-based access control for POS / Inventory / Administration.
Admin role receives wildcard (*) — all permissions.
"""

from .models import UserProfile

# ---------------------------------------------------------------------------
# Permission catalog (code -> human label, module grouping)
# ---------------------------------------------------------------------------

PERMISSION_CATALOG = {
    # Main navigation
    "dashboard.view": {"label": "Dashboard", "module": "dashboard"},
    # POS Terminal
    "pos.sell": {"label": "POS checkout & sell", "module": "pos"},
    "pos.hold": {"label": "Hold / resume orders", "module": "pos"},
    "pos.view": {"label": "POS Terminal", "module": "pos"},
    # Shifts & cash
    "shift.open": {"label": "Open cashier shift", "module": "shifts"},
    "shift.close": {"label": "Close cashier shift", "module": "shifts"},
    "shift.view": {"label": "View shifts", "module": "shifts"},
    "cash.manage": {"label": "Cash in / out & drawer", "module": "shifts"},
    # Sales control
    "sales.view": {"label": "View transactions", "module": "sales"},
    "sales.control": {"label": "Sales control dashboard", "module": "sales"},
    "sale.void": {"label": "Void sales", "module": "sales"},
    "sale.reprint": {"label": "Reprint receipts", "module": "sales"},
    "sale.refund": {"label": "Create refunds / returns", "module": "sales"},
    "sale.refund.approve": {"label": "Approve refunds", "module": "sales"},
    "sale.discount": {"label": "Apply discounts", "module": "sales"},
    "sales.payments": {"label": "Payments", "module": "sales"},
    "sales.discounts": {"label": "Discounts Log", "module": "sales"},
    "sales.customer": {"label": "Customer Sales", "module": "sales"},
    "sales.audit": {"label": "Sales Audit Logs", "module": "sales"},
    # Inventory
    "inventory.view": {"label": "View inventory", "module": "inventory"},
    "inventory.products": {"label": "Manage products", "module": "inventory"},
    "inventory.categories": {"label": "Manage categories", "module": "inventory"},
    "inventory.suppliers": {"label": "Manage suppliers", "module": "inventory"},
    "inventory.adjust": {"label": "Stock adjustments", "module": "inventory"},
    "purchase_order.create": {"label": "Create purchase orders", "module": "inventory"},
    "purchase_order.receive": {"label": "Receive goods", "module": "inventory"},
    "purchase_order.cancel": {"label": "Cancel purchase orders", "module": "inventory"},
    "stocktake.manage": {"label": "Stocktake sessions", "module": "inventory"},
    "inventory.variance": {"label": "Monthly Variance", "module": "inventory"},
    "inventory.warehouses": {"label": "Warehouses", "module": "inventory"},
    "inventory.reports": {"label": "Inventory Reports", "module": "inventory"},
    # Reports
    "reports.view": {"label": "View reports", "module": "reports"},
    "reports.export": {"label": "Export reports", "module": "reports"},
    "alerts.view": {"label": "Alerts", "module": "general"},
    "settings.view": {"label": "Settings", "module": "general"},
    # Administration
    "admin.company": {"label": "Manage companies (super)", "module": "admin"},
    "admin.company.view": {"label": "View company profile", "module": "admin"},
    "admin.branches": {"label": "Manage branches", "module": "admin"},
    "admin.users": {"label": "Manage users", "module": "admin"},
    "admin.roles": {"label": "View roles & permissions", "module": "admin"},
    "admin.settings": {"label": "System & module settings", "module": "admin"},
    "admin.security": {"label": "Security settings", "module": "admin"},
    "admin.audit": {"label": "Audit logs", "module": "admin"},
    "admin.notifications": {"label": "Notification rules", "module": "admin"},
    "admin.financial": {"label": "Financial controls", "module": "admin"},
    "admin.pricing": {"label": "Pricing controls", "module": "admin"},
    "admin.backup": {"label": "Backup & data export", "module": "admin"},
    "admin.integrations": {"label": "Integrations", "module": "admin"},
    "admin.super": {"label": "Super admin platform", "module": "admin"},
    "admin.reports": {"label": "Administration reports", "module": "admin"},
    "admin.scheduled_reports": {"label": "Scheduled email reports", "module": "admin"},
}

# Maps Administration UI sections to required permission (any one grants access; * always wins)
ADMIN_SECTION_PERMISSIONS = {
    "Business Setup": ["admin.company", "admin.company.view"],
    "Branches": ["admin.branches"],
    "Users": ["admin.users"],
    "Roles & Permissions": ["admin.roles"],
    "Security": ["admin.security", "admin.settings"],
    "System Settings": ["admin.settings"],
    "POS Operations": ["admin.settings"],
    "Stock Controls": ["admin.settings"],
    "Audit Logs": ["admin.audit"],
    "Notifications": ["admin.notifications", "admin.settings"],
    "Financial Control": ["admin.financial", "admin.settings"],
    "Pricing Control": ["admin.pricing", "admin.settings"],
    "Backup & Data": ["admin.backup", "admin.settings"],
    "Integrations": ["admin.integrations", "admin.settings"],
    "Super Admin": ["admin.super"],
    "Reports": ["admin.reports", "reports.view"],
    "Scheduled Reports": ["admin.scheduled_reports", "admin.reports", "admin.notifications"],
    "Alerts": ["alerts.view"],
    "Settings": ["settings.view", "admin.settings"],
}

ALL_PERMISSION_CODES = list(PERMISSION_CATALOG.keys())

CASHIER_PERMISSIONS = [
    "dashboard.view",
    "pos.sell", "pos.hold", "pos.view",
    "shift.open", "shift.close", "shift.view",
    "sales.view",
]

MANAGER_PERMISSIONS = CASHIER_PERMISSIONS + [
    "cash.manage",
    "sales.control",
    "sale.void", "sale.reprint", "sale.refund", "sale.discount",
    "reports.view", "reports.export",
    "inventory.view",
    "admin.audit",
    "admin.notifications",
    "financial.view",
    "admin.financial",
]

INVENTORY_PERMISSIONS = [
    "inventory.view", "inventory.products", "inventory.categories",
    "inventory.suppliers", "inventory.adjust",
    "purchase_order.create", "purchase_order.receive", "purchase_order.cancel",
    "stocktake.manage",
    "reports.view",
    "admin.audit",
]

ADMIN_PERMISSIONS = ["*"]

ROLE_PERMISSIONS = {
    UserProfile.CASHIER: CASHIER_PERMISSIONS,
    UserProfile.MANAGER: MANAGER_PERMISSIONS,
    UserProfile.INVENTORY: INVENTORY_PERMISSIONS,
    UserProfile.ADMIN: ADMIN_PERMISSIONS,
}

# Access-level extras merged at login (additive to role permissions)
ACCESS_LEVEL_PERMISSIONS = {
    UserProfile.SUPER_ADMIN: ["admin.super", "admin.company", "admin.scheduled_reports", "admin.reports"],
    UserProfile.COMPANY_ADMIN: ["admin.branches", "admin.users", "admin.roles", "admin.settings", "admin.scheduled_reports", "admin.reports"],
    UserProfile.BRANCH_ADMIN: ["admin.users", "admin.roles", "admin.scheduled_reports"],
    UserProfile.BRANCH_STAFF: [],
}


def permissions_for_profile(profile):
    """Resolve effective permission list for a user profile.

    Priority:
      1. If permission groups are assigned → use their combined permissions exclusively.
      2. If no groups → use role-based permissions (role + access level).
    """
    if not profile:
        return []
    # Groups win — they fully define the rights (no mixing with role)
    try:
        groups = list(profile.permission_groups.all())
        if groups:
            group_perms = set()
            for group in groups:
                group_perms.update(group.permissions or [])
            return sorted(group_perms)
    except Exception:
        pass
    # No groups: fall back to role permissions
    if getattr(profile, "use_custom_permissions", False):
        return sorted(set(getattr(profile, "custom_permissions", []) or []))
    perms = set(ROLE_PERMISSIONS.get(profile.role, []))
    perms.update(ACCESS_LEVEL_PERMISSIONS.get(profile.access_level, []))
    return sorted(perms)


def has_permission(user_permissions, code):
    if "*" in user_permissions:
        return True
    return code in user_permissions


def can_access_admin_section(user_permissions, section_name):
    if "*" in user_permissions:
        return True
    required = ADMIN_SECTION_PERMISSIONS.get(section_name, [])
    return any(code in user_permissions for code in required)


def role_permission_matrix():
    """Roles x permissions for UI matrix."""
    roles = [{"value": v, "label": l} for v, l in UserProfile.ROLE_CHOICES]
    matrix = []
    for role_value, _ in UserProfile.ROLE_CHOICES:
        perms = set(ROLE_PERMISSIONS.get(role_value, []))
        if "*" in perms:
            granted = ALL_PERMISSION_CODES
        else:
            granted = sorted(perms)
        matrix.append({
            "role": role_value,
            "permissions": granted,
            "permission_count": len(granted),
            "has_all": "*" in perms,
        })
    return {"roles": roles, "matrix": matrix, "catalog": PERMISSION_CATALOG}
