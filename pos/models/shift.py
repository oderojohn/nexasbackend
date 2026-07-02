from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from ._base import SyncMixin, TimeStampedModel
from .company import Branch


class Register(TimeStampedModel):
    branch = models.ForeignKey(Branch, related_name="registers", on_delete=models.PROTECT)
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "code"], name="unique_register_per_branch"),
        ]

    def __str__(self):
        return f"{self.branch.code}-{self.code}"


class Shift(SyncMixin, TimeStampedModel):
    OPEN = "open"
    CLOSED = "closed"
    STATUS_CHOICES = [(OPEN, "Open"), (CLOSED, "Closed")]

    branch = models.ForeignKey(Branch, related_name="shifts", on_delete=models.PROTECT)
    register = models.ForeignKey(Register, related_name="shifts", on_delete=models.PROTECT)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="pos_shifts", on_delete=models.PROTECT
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cash_variance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["register"],
                condition=models.Q(status="open"),
                name="one_open_shift_per_register",
            ),
        ]
        ordering = ["-opened_at"]

    def __str__(self):
        return f"{self.register} {self.cashier} {self.status}"


class CashTransaction(SyncMixin, TimeStampedModel):
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    PAYOUT = "payout"
    DROP = "drop"
    TYPE_CHOICES = [
        (CASH_IN, "Cash In"),
        (CASH_OUT, "Cash Out"),
        (PAYOUT, "Payout"),
        (DROP, "Cash Drop"),
    ]

    shift = models.ForeignKey(Shift, related_name="cash_transactions", on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, related_name="cash_transactions", on_delete=models.PROTECT)
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    reason = models.CharField(max_length=240, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]
