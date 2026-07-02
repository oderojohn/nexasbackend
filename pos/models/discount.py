from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from ._base import TimeStampedModel
from .company import Branch
from .product import Category, Product


class DiscountRule(TimeStampedModel):
    """Scheduled discount rule — applies at checkout when is_active_now() is True."""
    PERCENT = "percent"
    FIXED = "fixed"
    TYPE_CHOICES = [(PERCENT, "Percentage (%)"), (FIXED, "Fixed Amount (KES)")]

    ALL_PRODUCTS = "all"
    BY_CATEGORY = "category"
    BY_PRODUCT = "product"
    TARGET_CHOICES = [
        (ALL_PRODUCTS, "All Products"),
        (BY_CATEGORY, "Category"),
        (BY_PRODUCT, "Specific Product"),
    ]

    branch = models.ForeignKey(Branch, related_name="discount_rules", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    discount_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    target = models.CharField(max_length=10, choices=TARGET_CHOICES, default=ALL_PRODUCTS)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="discount_rules"
    )
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="discount_rules"
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    days_of_week = models.JSONField(default=list, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_discount_rules",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.branch})"

    def is_active_now(self):
        if not self.is_active:
            return False
        now = timezone.localtime()
        today = now.date()
        current_time = now.time()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        if self.days_of_week:
            if today.weekday() not in self.days_of_week:
                return False
        if self.start_time and current_time < self.start_time:
            return False
        if self.end_time and current_time > self.end_time:
            return False
        return True


class DiscountRuleLog(models.Model):
    """Audit trail for every create / update / delete on a DiscountRule."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    ACTION_CHOICES = [
        (CREATED, "Created"),
        (UPDATED, "Updated"),
        (DELETED, "Deleted"),
        (ACTIVATED, "Activated"),
        (DEACTIVATED, "Deactivated"),
    ]

    branch = models.ForeignKey(Branch, related_name="discount_rule_logs", on_delete=models.CASCADE)
    rule = models.ForeignKey(
        DiscountRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    rule_name = models.CharField(max_length=120)
    rule_snapshot = models.JSONField(default=dict)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="discount_rule_logs",
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at"]
        indexes = [models.Index(fields=["branch", "-performed_at"])]

    def __str__(self):
        return f"{self.action} — {self.rule_name} ({self.performed_at:%Y-%m-%d %H:%M})"


class PriceSchedule(TimeStampedModel):
    """Schedule a product price change to take effect at a specific datetime."""
    branch = models.ForeignKey(Branch, related_name="price_schedules", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="price_schedules", on_delete=models.CASCADE)
    new_retail_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    new_wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    effective_at = models.DateTimeField()
    applied_at = models.DateTimeField(null=True, blank=True)
    is_applied = models.BooleanField(default=False, db_index=True)
    note = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_price_schedules",
    )

    class Meta:
        ordering = ["effective_at"]

    def __str__(self):
        return f"{self.product.name} @ {self.effective_at}"


class PriceScheduleLog(models.Model):
    """Audit trail for every create / update / delete / apply on a PriceSchedule."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    APPLIED = "applied"
    ACTION_CHOICES = [
        (CREATED, "Created"),
        (UPDATED, "Updated"),
        (DELETED, "Deleted"),
        (APPLIED, "Applied"),
    ]

    branch = models.ForeignKey(Branch, related_name="price_schedule_logs", on_delete=models.CASCADE)
    schedule = models.ForeignKey(
        PriceSchedule, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    product_name = models.CharField(max_length=240)
    schedule_snapshot = models.JSONField(default=dict)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="price_schedule_logs",
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at"]
        indexes = [models.Index(fields=["branch", "-performed_at"])]

    def __str__(self):
        return f"{self.action} — {self.product_name} ({self.performed_at:%Y-%m-%d %H:%M})"
