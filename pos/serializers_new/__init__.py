from ._helpers import _request_user, _validate_branch_access, _validate_same_branch
from .auth import LoginSerializer, PermissionGroupSerializer, SwitchBranchSerializer, UserProfileSerializer
from .company import BranchSerializer, CompanySerializer, CompanySettingsSerializer
from .customer import CustomerSerializer, SupplierSerializer
from .inventory import (
    ApproveStocktakeSerializer,
    AuditLogSerializer,
    CountStocktakeItemSerializer,
    CountStocktakeSerializer,
    CreatePurchaseOrderSerializer,
    CreateStocktakeSerializer,
    PurchaseOrderItemInputSerializer,
    PurchaseOrderItemSerializer,
    PurchaseOrderSerializer,
    ReceiveItemSerializer,
    ReceivePurchaseOrderSerializer,
    StockAdjustmentSerializer,
    StocktakeItemSerializer,
    StocktakeSessionSerializer,
    StockMovementSerializer,
    UpdatePurchaseOrderSerializer,
)
from .mpesa import (
    MpesaDirectLookupSerializer,
    MpesaDirectPaymentLogSerializer,
    MpesaStkLogSerializer,
    MpesaStkPushSerializer,
    MpesaStkQuerySerializer,
)
from .product import CategoryPKField, CategorySerializer, InventoryStockSerializer, ProductSerializer
from .reports import ReportScheduleSerializer
from .returns import (
    ApproveSaleReturnSerializer,
    CompleteSaleReturnSerializer,
    CreateSaleReturnItemSerializer,
    CreateSaleReturnSerializer,
    RejectSaleReturnSerializer,
    SaleReturnItemSerializer,
    SaleReturnSerializer,
)
from .sale import (
    CheckoutItemSerializer,
    CheckoutPaymentSerializer,
    CheckoutSerializer,
    HeldOrderItemSerializer,
    HeldOrderSerializer,
    HoldOrderItemInputSerializer,
    HoldOrderSerializer,
    PaymentSerializer,
    ReceiptCopySerializer,
    ReprintReceiptSerializer,
    SaleItemSerializer,
    SaleSerializer,
    UpdateHoldOrderSerializer,
    VoidSaleSerializer,
)
from .shift import (
    CashTransactionSerializer,
    CloseShiftSerializer,
    CreateCashTransactionSerializer,
    OpenShiftSerializer,
    RegisterSerializer,
    ShiftSerializer,
)

__all__ = [
    # helpers (consumed by views)
    "_request_user",
    "_validate_branch_access",
    "_validate_same_branch",
    # auth
    "LoginSerializer",
    "PermissionGroupSerializer",
    "SwitchBranchSerializer",
    "UserProfileSerializer",
    # company
    "BranchSerializer",
    "CompanySerializer",
    "CompanySettingsSerializer",
    # customer
    "CustomerSerializer",
    "SupplierSerializer",
    # inventory
    "ApproveStocktakeSerializer",
    "AuditLogSerializer",
    "CountStocktakeItemSerializer",
    "CountStocktakeSerializer",
    "CreatePurchaseOrderSerializer",
    "CreateStocktakeSerializer",
    "PurchaseOrderItemInputSerializer",
    "PurchaseOrderItemSerializer",
    "PurchaseOrderSerializer",
    "ReceiveItemSerializer",
    "ReceivePurchaseOrderSerializer",
    "StockAdjustmentSerializer",
    "StocktakeItemSerializer",
    "StocktakeSessionSerializer",
    "StockMovementSerializer",
    "UpdatePurchaseOrderSerializer",
    # mpesa
    "MpesaDirectLookupSerializer",
    "MpesaDirectPaymentLogSerializer",
    "MpesaStkLogSerializer",
    "MpesaStkPushSerializer",
    "MpesaStkQuerySerializer",
    # product
    "CategoryPKField",
    "CategorySerializer",
    "InventoryStockSerializer",
    "ProductSerializer",
    # reports
    "ReportScheduleSerializer",
    # returns
    "ApproveSaleReturnSerializer",
    "CompleteSaleReturnSerializer",
    "CreateSaleReturnItemSerializer",
    "CreateSaleReturnSerializer",
    "RejectSaleReturnSerializer",
    "SaleReturnItemSerializer",
    "SaleReturnSerializer",
    # sale
    "CheckoutItemSerializer",
    "CheckoutPaymentSerializer",
    "CheckoutSerializer",
    "HeldOrderItemSerializer",
    "HeldOrderSerializer",
    "HoldOrderItemInputSerializer",
    "HoldOrderSerializer",
    "PaymentSerializer",
    "ReceiptCopySerializer",
    "ReprintReceiptSerializer",
    "SaleItemSerializer",
    "SaleSerializer",
    "UpdateHoldOrderSerializer",
    "VoidSaleSerializer",
    # shift
    "CashTransactionSerializer",
    "CloseShiftSerializer",
    "CreateCashTransactionSerializer",
    "OpenShiftSerializer",
    "RegisterSerializer",
    "ShiftSerializer",
]
