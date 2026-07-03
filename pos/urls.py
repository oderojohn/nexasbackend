from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .admin_settings import AdminRbacViewSet, CompanySettingsViewSet
from .sales_control import CashTransactionViewSet, PaymentViewSet, SaleReturnViewSet
from .views import (
    AuditLogViewSet,
    AuthViewSet,
    BranchViewSet,
    CategoryViewSet,
    CompanyViewSet,
    CustomerViewSet,
    HeldOrderViewSet,
    InventoryStockViewSet,
    ProductViewSet,
    PurchaseOrderViewSet,
    RegisterViewSet,
    SaleViewSet,
    ShiftViewSet,
    StockMovementViewSet,
    StocktakeViewSet,
    UserProfileViewSet,
    MpesaDirectPaymentLogViewSet,
    MpesaStkLogViewSet,
    mpesa_callback,
    mpesa_direct_callback,
)
from .views_credit_loyalty_reports import CreditLoyaltyReportsViewSet
from .views_discounts import DiscountRuleViewSet, PriceScheduleViewSet
from .views_groups import PermissionGroupViewSet
from .views_notifications import pos_notifications
from .views_reports import ReportScheduleViewSet
from .views_sync import (
    device_checkin, device_manage, device_register, devices_list,
    generate_pairing_token, local_bootstrap, pair_device,
    sync_pull, sync_push, validate_pairing_token,
)
from .views_system_health import system_health


router = DefaultRouter()
router.register("admin-settings", CompanySettingsViewSet, basename="admin-settings")
router.register("admin-rbac", AdminRbacViewSet, basename="admin-rbac")
router.register("auth", AuthViewSet, basename="auth")
router.register("users", UserProfileViewSet)
router.register("companies", CompanyViewSet)
router.register("branches", BranchViewSet)
router.register("registers", RegisterViewSet)
router.register("categories", CategoryViewSet)
router.register("products", ProductViewSet)
router.register("stock", InventoryStockViewSet)
router.register("customers", CustomerViewSet)
router.register("shifts", ShiftViewSet)
router.register("sales", SaleViewSet)
router.register("sale-returns", SaleReturnViewSet, basename="sale-returns")
router.register("payments", PaymentViewSet, basename="payments")
router.register("cash-transactions", CashTransactionViewSet, basename="cash-transactions")
router.register("held-orders", HeldOrderViewSet)
router.register("stock-movements", StockMovementViewSet)
router.register("audit-logs", AuditLogViewSet)
router.register("purchase-orders", PurchaseOrderViewSet)
router.register("stocktakes", StocktakeViewSet)
router.register("discount-rules", DiscountRuleViewSet, basename="discount-rules")
router.register("price-schedules", PriceScheduleViewSet, basename="price-schedules")
router.register("report-schedules", ReportScheduleViewSet, basename="report-schedules")
router.register("permission-groups", PermissionGroupViewSet, basename="permission-groups")
router.register("mpesa-stk-logs", MpesaStkLogViewSet, basename="mpesa-stk-logs")
router.register("mpesa-direct-logs", MpesaDirectPaymentLogViewSet, basename="mpesa-direct-logs")
router.register("credit-loyalty-reports", CreditLoyaltyReportsViewSet, basename="credit-loyalty-reports")

urlpatterns = [
    path("mpesa/callback", mpesa_callback, name="mpesa-callback"),
    path("mpesa/callback/", mpesa_callback, name="mpesa-callback-slash"),
    path("mpesa/direct-callback", mpesa_direct_callback, name="mpesa-direct-callback"),
    path("mpesa/direct-callback/", mpesa_direct_callback, name="mpesa-direct-callback-slash"),
    path("sync/device-register/", device_register, name="sync-device-register"),
    path("sync/devices/", devices_list, name="sync-devices"),
    path("sync/devices/<uuid:device_uuid>/", device_manage, name="sync-device-manage"),
    path("sync/device-checkin/", device_checkin, name="sync-device-checkin"),
    path("sync/push/", sync_push, name="sync-push"),
    path("sync/pull/", sync_pull, name="sync-pull"),
    path("sync/generate-pairing-token/", generate_pairing_token, name="sync-generate-pairing-token"),
    path("sync/validate-token/", validate_pairing_token, name="sync-validate-token"),
    path("sync/pair-device/", pair_device, name="sync-pair-device"),
    path("sync/local-bootstrap/", local_bootstrap, name="sync-local-bootstrap"),
    path("pos-notifications/", pos_notifications, name="pos-notifications"),
    path("system-health/", system_health, name="system-health"),
    path("", include(router.urls)),
]
