from decimal import Decimal

from django.conf import settings
from django.db import models

from ._base import SyncMixin, TimeStampedModel
from .company import Branch
from .product import Product


class InventoryStock(TimeStampedModel):
    branch = models.ForeignKey(Branch, related_name="inventory", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="stock_rows", on_delete=models.CASCADE)
    quantity = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "product"], name="unique_product_stock_per_branch"),
            models.CheckConstraint(check=models.Q(quantity__gte=0), name="stock_quantity_cannot_be_negative"),
        ]

    def __str__(self):
        return f"{self.branch.code} {self.product.sku}: {self.quantity}"


class StockMovement(SyncMixin, TimeStampedModel):
    SALE = "sale"
    VOID = "void"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    RECEIVE = "receive"
    HOLD_RELEASE = "hold_release"
    REASON_CHOICES = [
        (SALE, "Sale"),
        (VOID, "Void"),
        (RETURN, "Return"),
        (ADJUSTMENT, "Adjustment"),
        (RECEIVE, "Receive"),
        (HOLD_RELEASE, "Hold Release"),
    ]

    branch = models.ForeignKey(Branch, related_name="stock_movements", on_delete=models.PROTECT)
    product = models.ForeignKey(Product, related_name="stock_movements", on_delete=models.PROTECT)
    quantity_delta = models.IntegerField()
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    reference = models.CharField(max_length=80, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]


class AuditLog(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=80)
    entity = models.CharField(max_length=80, blank=True)
    entity_id = models.CharField(max_length=80, blank=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class PurchaseOrder(SyncMixin, TimeStampedModel):
    DRAFT = "draft"
    ORDERED = "ordered"
    PARTIAL = "partial"
    RECEIVED = "received"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (ORDERED, "Ordered"),
        (PARTIAL, "Partial"),
        (RECEIVED, "Received"),
        (CANCELLED, "Cancelled"),
    ]

    po_no = models.CharField(max_length=40, unique=True)
    branch = models.ForeignKey(Branch, related_name="purchase_orders", on_delete=models.PROTECT)
    supplier = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    expected_at = models.DateField(null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.po_no


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    ordered_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    @property
    def line_total(self):
        return self.ordered_quantity * self.unit_cost


class StocktakeSession(TimeStampedModel):
    OPEN = "open"
    COUNTED = "counted"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (OPEN, "Open"),
        (COUNTED, "Counted"),
        (APPROVED, "Approved"),
        (CANCELLED, "Cancelled"),
    ]

    session_no = models.CharField(max_length=40, unique=True)
    branch = models.ForeignKey(Branch, related_name="stocktakes", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        related_name="approved_stocktakes", on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.session_no


class StocktakeItem(models.Model):
    stocktake = models.ForeignKey(StocktakeSession, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    system_quantity = models.IntegerField(default=0)
    counted_quantity = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stocktake", "product"], name="unique_product_per_stocktake"),
        ]

    @property
    def variance(self):
        return self.counted_quantity - self.system_quantity
