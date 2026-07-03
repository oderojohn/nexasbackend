from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from ._base import SyncMixin, TimeStampedModel
from .company import Branch


class Customer(SyncMixin, TimeStampedModel):
    """
    Scoped to a branch. Company is derivable via customer.branch.company.
    """
    branch = models.ForeignKey(Branch, related_name="customers", on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=240, blank=True)
    tax_pin = models.CharField(max_length=40, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    loyalty_points = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "phone"], condition=Q(phone__gt=""), name="unique_customer_phone_per_branch"),
        ]

    def __str__(self):
        return self.name


class CreditRepayment(TimeStampedModel):
    """A repayment recorded against a customer's outstanding credit balance."""
    customer = models.ForeignKey(Customer, related_name="credit_repayments", on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, related_name="credit_repayments", on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer.name} paid {self.amount}"


class LoyaltyTransaction(TimeStampedModel):
    EARN = "earn"
    REDEEM = "redeem"
    ADJUSTMENT = "adjustment"
    TYPE_CHOICES = [(EARN, "Earned"), (REDEEM, "Redeemed"), (ADJUSTMENT, "Adjustment")]

    customer = models.ForeignKey(Customer, related_name="loyalty_transactions", on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, related_name="loyalty_transactions", on_delete=models.CASCADE)
    points = models.IntegerField()
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    sale = models.ForeignKey("pos.Sale", null=True, blank=True, on_delete=models.SET_NULL)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer.name} {self.transaction_type} {self.points}"


class Supplier(SyncMixin, TimeStampedModel):
    """
    Scoped to a branch. Company is derivable via supplier.branch.company.
    """
    branch = models.ForeignKey(Branch, related_name="suppliers", on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="unique_supplier_per_branch"),
        ]

    def __str__(self):
        return self.name
