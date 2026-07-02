from decimal import Decimal

from django.conf import settings
from django.db import models

from ._base import SyncMixin, TimeStampedModel
from .company import Branch
from .customer import Customer
from .product import Product
from .shift import Register, Shift


class HeldOrder(SyncMixin, TimeStampedModel):
    OPEN = "open"
    RESUMED = "resumed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [(OPEN, "Open"), (RESUMED, "Resumed"), (CANCELLED, "Cancelled")]

    branch = models.ForeignKey(Branch, related_name="held_orders", on_delete=models.PROTECT)
    register = models.ForeignKey(Register, related_name="held_orders", on_delete=models.PROTECT)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="held_orders", on_delete=models.PROTECT
    )
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)

    class Meta:
        ordering = ["-created_at"]


class HeldOrderItem(models.Model):
    held_order = models.ForeignKey(HeldOrder, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class Sale(SyncMixin, TimeStampedModel):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    MODE_CHOICES = [(RETAIL, "Retail"), (WHOLESALE, "Wholesale")]

    DRAFT = "draft"
    PAID = "paid"
    VOIDED = "voided"
    STATUS_CHOICES = [(DRAFT, "Draft"), (PAID, "Paid"), (VOIDED, "Voided")]

    receipt_no = models.CharField(max_length=40, unique=True)
    branch = models.ForeignKey(Branch, related_name="sales", on_delete=models.PROTECT)
    register = models.ForeignKey(Register, related_name="sales", on_delete=models.PROTECT)
    shift = models.ForeignKey(Shift, related_name="sales", on_delete=models.PROTECT)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="sales", on_delete=models.PROTECT
    )
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=RETAIL)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    change_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        related_name="voided_sales", on_delete=models.SET_NULL,
    )
    void_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["receipt_no"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return self.receipt_no


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2)


class Payment(models.Model):
    CASH = "cash"
    CARD = "card"
    MPESA = "mpesa"
    CREDIT = "credit"
    METHOD_CHOICES = [(CASH, "Cash"), (CARD, "Card"), (MPESA, "M-Pesa"), (CREDIT, "Credit")]

    sale = models.ForeignKey(Sale, related_name="payments", on_delete=models.CASCADE)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MpesaStkLog(TimeStampedModel):
    branch = models.ForeignKey('pos.Branch', related_name='mpesa_stk_logs', null=True, blank=True, on_delete=models.SET_NULL)
    sale = models.ForeignKey('pos.Sale', related_name='mpesa_stk_logs', null=True, blank=True, on_delete=models.SET_NULL)
    payment = models.ForeignKey('pos.Payment', related_name='mpesa_stk_logs', null=True, blank=True, on_delete=models.SET_NULL)
    phone = models.CharField(max_length=40)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    request = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=False)
    message = models.CharField(max_length=255, blank=True)
    merchant_request_id = models.CharField(max_length=120, blank=True)
    checkout_request_id = models.CharField(max_length=120, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"MPESA STK {self.phone} {self.amount} {'OK' if self.success else 'FAIL'}"


class MpesaDirectPaymentLog(TimeStampedModel):
    branch = models.ForeignKey('pos.Branch', related_name='mpesa_direct_logs', null=True, blank=True, on_delete=models.SET_NULL)
    sale = models.ForeignKey('pos.Sale', related_name='mpesa_direct_logs', null=True, blank=True, on_delete=models.SET_NULL)
    payment = models.ForeignKey('pos.Payment', related_name='mpesa_direct_logs', null=True, blank=True, on_delete=models.SET_NULL)
    transaction_id = models.CharField(max_length=120, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    payer_name = models.CharField(max_length=160, blank=True)
    request = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=False)
    message = models.CharField(max_length=255, blank=True)
    originator_conversation_id = models.CharField(max_length=120, blank=True, db_index=True)
    conversation_id = models.CharField(max_length=120, blank=True, db_index=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"MPESA Direct {self.transaction_id} {'OK' if self.success else 'PENDING'}"


class ReceiptCopy(TimeStampedModel):
    sale = models.ForeignKey(Sale, related_name="receipt_copies", on_delete=models.CASCADE)
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    copy_no = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sale", "copy_no"], name="unique_receipt_copy_no"),
        ]


class SaleReturn(TimeStampedModel):
    PENDING = "pending"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (COMPLETED, "Completed"),
        (REJECTED, "Rejected"),
    ]

    return_no = models.CharField(max_length=40, unique=True)
    sale = models.ForeignKey(Sale, related_name="returns", on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, related_name="sale_returns", on_delete=models.PROTECT)
    shift = models.ForeignKey(
        Shift, null=True, blank=True, related_name="sale_returns", on_delete=models.SET_NULL
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="processed_returns", on_delete=models.PROTECT
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        related_name="approved_returns", on_delete=models.SET_NULL,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    reason = models.CharField(max_length=240)
    rejection_reason = models.CharField(max_length=240, blank=True)
    refund_method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES, default=Payment.CASH)
    subtotal_refund = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_refund = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_refund = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["return_no"]),
        ]

    def __str__(self):
        return self.return_no


class SaleReturnItem(models.Model):
    sale_return = models.ForeignKey(SaleReturn, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_refund = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sale_return", "product"], name="unique_product_per_return"),
        ]
