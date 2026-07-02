from django.conf import settings
from django.db import models
from django.utils import timezone

from ._base import TimeStampedModel
from .company import Branch, Company


class PermissionGroup(TimeStampedModel):
    """Named collection of permission codes that can be assigned to users."""
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='permission_groups'
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'name'], name='unique_perm_group_per_company'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.company})"


class UserProfile(TimeStampedModel):
    CASHIER = "cashier"
    MANAGER = "manager"
    INVENTORY = "inventory"
    ADMIN = "admin"
    ROLE_CHOICES = [
        (CASHIER, "Cashier"),
        (MANAGER, "Manager"),
        (INVENTORY, "Inventory Officer"),
        (ADMIN, "Administrator"),
    ]

    SUPER_ADMIN = "super_admin"
    COMPANY_ADMIN = "company_admin"
    BRANCH_ADMIN = "branch_admin"
    BRANCH_STAFF = "branch_staff"
    ACCESS_LEVEL_CHOICES = [
        (SUPER_ADMIN, "Super Admin"),
        (COMPANY_ADMIN, "Company Admin"),
        (BRANCH_ADMIN, "Branch Admin"),
        (BRANCH_STAFF, "Branch Staff"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="pos_profile", on_delete=models.CASCADE
    )
    pos_username = models.CharField(max_length=150, blank=True)
    pin = models.CharField(max_length=128, blank=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=CASHIER)
    access_level = models.CharField(
        max_length=30, choices=ACCESS_LEVEL_CHOICES, default=BRANCH_STAFF
    )
    branch = models.ForeignKey(
        Branch, null=True, blank=True,
        related_name="staff_profiles", on_delete=models.SET_NULL,
    )
    company = models.ForeignKey(
        Company, null=True, blank=True,
        related_name="staff_profiles", on_delete=models.SET_NULL,
    )
    custom_permissions = models.JSONField(default=list, blank=True)
    use_custom_permissions = models.BooleanField(default=False)
    permission_groups = models.ManyToManyField(
        'pos.PermissionGroup', blank=True, related_name='members'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "pos_username"],
                condition=models.Q(pos_username__gt=""),
                name="unique_pos_username_per_company",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.branch_id and self.company_id and self.branch.company_id != self.company_id:
            raise ValidationError({"company": "Company must match the branch's company."})

    def __str__(self):
        return f"{self.user} ({self.role}) - {self.get_access_level_display()}"


class BlacklistedToken(models.Model):
    """Revoked POS bearer tokens. Checked on every authenticated request."""
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blacklisted_tokens",
    )
    blacklisted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    @classmethod
    def is_blacklisted(cls, token_hash):
        import random
        if random.random() < 0.02:
            cls.objects.filter(expires_at__lt=timezone.now()).delete()
        return cls.objects.filter(token_hash=token_hash, expires_at__gt=timezone.now()).exists()
