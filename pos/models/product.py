from decimal import Decimal

from django.db import models

from ._base import SyncMixin, TimeStampedModel
from .company import Branch


class Category(SyncMixin, TimeStampedModel):
    """
    Scoped to a branch. Company is always derivable via category.branch.company.
    Each branch manages its own category list independently.
    """
    branch = models.ForeignKey(Branch, related_name="categories", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    color = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="unique_category_per_branch"),
        ]

    def __str__(self):
        return self.name


class Product(SyncMixin, TimeStampedModel):
    """
    Scoped to a branch. Stock levels are tracked via InventoryStock on the same branch.
    Company is always derivable via product.branch.company.
    """
    branch = models.ForeignKey(Branch, related_name="products", on_delete=models.CASCADE)
    category = models.ForeignKey(Category, related_name="products", on_delete=models.PROTECT)
    name = models.CharField(max_length=180)
    sku = models.CharField(max_length=60)
    barcode = models.CharField(max_length=80, blank=True, db_index=True)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    reorder_point = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["sku"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["branch", "is_active"], name="product_branch_active_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["branch", "sku"], name="unique_sku_per_branch"),
        ]

    def __str__(self):
        return self.name
