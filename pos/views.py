"""
Thin aggregator — imports and re-exports all viewsets and helpers so that
urls.py, sales_control.py, and admin_settings.py can keep importing from here
unchanged.  Do not add business logic here.
"""

# Helpers (imported by sales_control.py and admin_settings.py)
from .views_helpers import (  # noqa: F401
    _active_branch,
    _active_company,
    _audit,
    _auth_permissions_payload,
    _branch_filter_kwargs,
    _build_context_payload,
    _changed_fields,
    _csv_response,
    _filter_branch_scoped_queryset,
    _get_active_branch_by_id,
    _pdf_response,
    _positive_int_query_param,
    _positive_int_value,
    _resolve_read_branch,
    _resolve_write_branch,
    is_branch_admin,
    is_company_admin,
    is_super_admin,
)

# Auth / user viewsets
from .views_auth import AuthViewSet, UserProfileViewSet  # noqa: F401

# Company / product viewsets
from .views_company import (  # noqa: F401
    BranchViewSet,
    CategoryViewSet,
    CompanyViewSet,
    ProductViewSet,
    RegisterViewSet,
)

# Inventory viewsets
from .views_inventory import (  # noqa: F401
    InventoryStockViewSet,
    StockMovementViewSet,
    StocktakeViewSet,
)

# Customer / supplier viewsets
from .views_customers import CustomerViewSet, SupplierViewSet  # noqa: F401

# Sales viewsets
from .views_sales import HeldOrderViewSet, SaleViewSet, ShiftViewSet  # noqa: F401

# Purchasing / audit viewsets
from .views_purchasing import AuditLogViewSet, PurchaseOrderViewSet  # noqa: F401

# M-Pesa callbacks and log viewsets
from .views_mpesa import (  # noqa: F401
    MpesaDirectPaymentLogViewSet,
    MpesaStkLogViewSet,
    mpesa_callback,
    mpesa_direct_callback,
)

# Offline sync endpoints
from .views_sync import device_checkin, sync_pull, sync_push  # noqa: F401
