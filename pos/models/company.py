import re

from django.db import models

from ._base import TimeStampedModel


def default_company_settings():
    return {
        "security": {
            "pin_login_enabled": True,
            "two_factor_optional": True,
            "auto_logout_minutes": 15,
            "device_history": True,
            "force_logout_admin_only": True,
        },
        "system": {
            "tax_mode": "inclusive",
            "receipt_prefix": "RC",
            "invoice_prefix": "INV",
            "return_prefix": "RET",
            "printer_type": "thermal_80mm",
        },
        "pos_operations": {
            "discounts_enabled": True,
            "refunds_manager_approval": True,
            "credit_sales_enabled": True,
            "layby_enabled": False,
            "barcode_mode": True,
            "max_cashier_discount_pct": 5,
        },
        "stock_controls": {
            "auto_deduct_on_sale": True,
            "branch_stock_separation": True,
            "transfer_approval_required": True,
            "low_stock_alerts": True,
            "stock_adjustment_approval": True,
        },
        "notifications": {
            "low_stock": {"sms": False, "email": True, "whatsapp": False, "recipients": "inventory"},
            "daily_sales": {"sms": False, "email": True, "whatsapp": False, "recipients": "managers"},
            "refund_alerts": {"sms": True, "email": True, "whatsapp": False, "recipients": "managers"},
            "suspicious_activity": {"sms": False, "email": True, "whatsapp": True, "recipients": "admins"},
        },
        "financial": {
            "daily_cash_summaries": True,
            "cash_drawer_tracking": True,
            "z_report_required": True,
            "cash_discrepancy_tracking": True,
            "payment_methods": "cash,mpesa,card",
        },
        "pricing": {
            "retail_price_edits": "manager",
            "wholesale_price_edits": "admin",
            "max_cashier_discount_pct": 5,
            "product_deactivation": "admin",
            "price_change_workflow": True,
        },
        "backup": {
            "auto_backup_enabled": True,
            "auto_backup_time": "01:00",
            "manual_download": True,
            "restore_admin_only": True,
            "csv_export": True,
            "archive_months": 24,
        },
        "integrations": {
            "mpesa": {"status": "connected", "mode": "live", "notes": "Callbacks enabled"},
            "thermal_printers": {"status": "ready", "mode": "usb_network", "notes": "80mm default"},
            "barcode_scanners": {"status": "supported", "mode": "keyboard_wedge", "notes": "Plug and play"},
            "accounting": {"status": "optional", "mode": "api", "notes": "Export journal entries"},
            "api_keys": {"status": "managed", "mode": "admin_only", "notes": "Rotate every 90 days"},
        },
        "super_admin": {
            "manage_all_businesses": True,
            "suspend_companies": True,
            "view_all_transactions": True,
            "force_logout_users": True,
            "maintenance_mode": False,
        },
        "email_config": {
            "backend": "smtp",
            "host": "",
            "port": 587,
            "use_tls": True,
            "username": "",
            "password": "",
            "from_email": "",
            "from_name": "Nexa POS",
        },
        "cloud_config": {
            "cloud_api_url": "",
            "cloud_sync_token": "",
            "branch_id": "",
        },
    }


class Company(TimeStampedModel):
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=20, unique=True)
    currency = models.CharField(max_length=10, default="KES")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Companies"

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def generate_code(cls, name):
        base = re.sub(r"[^A-Z0-9]", "", (name or "").upper())[:10] or "CO"
        candidate = base
        suffix = 1
        while cls.objects.filter(code=candidate).exists():
            suffix += 1
            candidate = f"{base}{suffix}"
        return candidate


class CompanySettings(TimeStampedModel):
    company = models.OneToOneField(Company, related_name="settings", on_delete=models.CASCADE)
    security = models.JSONField(default=dict, blank=True)
    system = models.JSONField(default=dict, blank=True)
    pos_operations = models.JSONField(default=dict, blank=True)
    stock_controls = models.JSONField(default=dict, blank=True)
    notifications = models.JSONField(default=dict, blank=True)
    financial = models.JSONField(default=dict, blank=True)
    pricing = models.JSONField(default=dict, blank=True)
    backup = models.JSONField(default=dict, blank=True)
    integrations = models.JSONField(default=dict, blank=True)
    super_admin = models.JSONField(default=dict, blank=True)
    email_config = models.JSONField(default=dict, blank=True)
    cloud_config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "Company settings"

    def merged_settings(self):
        defaults = default_company_settings()
        return {
            "security": {**defaults["security"], **(self.security or {})},
            "system": {**defaults["system"], **(self.system or {})},
            "pos_operations": {**defaults["pos_operations"], **(self.pos_operations or {})},
            "stock_controls": {**defaults["stock_controls"], **(self.stock_controls or {})},
            "notifications": {**defaults["notifications"], **(self.notifications or {})},
            "financial": {**defaults["financial"], **(self.financial or {})},
            "pricing": {**defaults["pricing"], **(self.pricing or {})},
            "backup": {**defaults["backup"], **(self.backup or {})},
            "integrations": {**defaults["integrations"], **(self.integrations or {})},
            "super_admin": {**defaults["super_admin"], **(self.super_admin or {})},
            "email_config": {**defaults["email_config"], **(self.email_config or {})},
            "cloud_config": {**defaults["cloud_config"], **(self.cloud_config or {})},
        }


class Branch(TimeStampedModel):
    ENVIRONMENT_CHOICES = [
        ("sandbox", "Sandbox"),
        ("live", "Live"),
    ]

    company = models.ForeignKey(Company, related_name="branches", on_delete=models.CASCADE)
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=True)
    mpesa_stk_enabled = models.BooleanField(default=False)
    mpesa_manual_approval_enabled = models.BooleanField(default=False)
    mpesa_till_enabled = models.BooleanField(default=False)
    mpesa_consumer_key = models.CharField(max_length=255, blank=True)
    mpesa_consumer_secret = models.CharField(max_length=255, blank=True)
    mpesa_business_shortcode = models.CharField(max_length=64, blank=True)
    mpesa_passkey = models.CharField(max_length=255, blank=True)
    mpesa_environment = models.CharField(max_length=16, choices=ENVIRONMENT_CHOICES, default="sandbox", blank=True)
    mpesa_callback_url = models.CharField(max_length=255, blank=True)
    mpesa_till_number = models.CharField(max_length=64, blank=True)
    mpesa_initiator_name = models.CharField(max_length=120, blank=True)
    mpesa_security_credential = models.CharField(max_length=1024, blank=True)
    mpesa_direct_result_url = models.CharField(max_length=255, blank=True)
    mpesa_direct_timeout_url = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="unique_branch_code_per_company",
            ),
        ]

    def __str__(self):
        return f"{self.company.name} — {self.name}"
