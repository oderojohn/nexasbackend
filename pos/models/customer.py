from decimal import Decimal

from django.db import models

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
    tax_pin = models.CharField(max_length=40, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    loyalty_points = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


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
