from django.contrib import admin

from .models import (
    AuditLog,
    Branch,
    Category,
    Company,
    Customer,
    HeldOrder,
    InventoryStock,
    Payment,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceiptCopy,
    Register,
    Sale,
    SaleItem,
    Shift,
    StocktakeItem,
    StocktakeSession,
    StockMovement,
    UserProfile,
    MpesaDirectPaymentLog,
    MpesaStkLog,
)


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0


class StocktakeItemInline(admin.TabularInline):
    model = StocktakeItem
    extra = 0


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "currency", "vat_rate", "is_active", "created_at")
    list_filter = ("is_active", "currency")
    search_fields = ("name", "code", "id")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Company Info", {
            "fields": ("name", "code", "currency", "vat_rate")
        }),
        ("Status", {
            "fields": ("is_active",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "company", "location", "is_active", "created_at")
    list_filter = ("is_active", "company")
    search_fields = ("name", "code", "location")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ["company"]
    
    fieldsets = (
        ("Branch Info", {
            "fields": ("company", "name", "code", "location")
        }),
        ("M-Pesa Settings", {
            "fields": (
                "mpesa_consumer_key",
                "mpesa_consumer_secret",
                "mpesa_stk_enabled",
                "mpesa_manual_approval_enabled",
                "mpesa_business_shortcode",
                "mpesa_passkey",
                "mpesa_environment",
                "mpesa_callback_url",
                "mpesa_till_enabled",
                "mpesa_till_number",
                "mpesa_initiator_name",
                "mpesa_security_credential",
                "mpesa_direct_result_url",
                "mpesa_direct_timeout_url",
            )
        }),
        ("Status", {
            "fields": ("is_active",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "branch", "register", "cashier", "status", "total", "created_at")
    search_fields = ("receipt_no", "customer__name")
    list_filter = ("status", "branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "mode")
    inlines = [SaleItemInline, PaymentInline]


@admin.register(Register)
class RegisterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "branch", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "is_active", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "is_active")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "branch", "category", "retail_price", "wholesale_price", "is_active", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "category", "is_active")
    search_fields = ("name", "sku", "barcode")
    readonly_fields = ("created_at", "updated_at")


@admin.register(InventoryStock)
class InventoryStockAdmin(admin.ModelAdmin):
    list_display = ("branch", "product", "quantity", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    search_fields = ("product__name", "product__sku")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("branch", "product", "reason", "quantity_delta", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "reason")
    search_fields = ("product__name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "phone", "email", "is_active", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "is_active")
    search_fields = ("name", "phone", "email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("branch", "register", "cashier", "status", "opened_at", "closed_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "status")
    search_fields = ("cashier__username", "register__code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(HeldOrder)
class HeldOrderAdmin(admin.ModelAdmin):
    list_display = ("branch", "register", "cashier", "status", "created_at")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter), "status")
    search_fields = ("cashier__username", "note")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ReceiptCopy)
class ReceiptCopyAdmin(admin.ModelAdmin):
    list_display = ("sale", "copy_no", "printed_by", "created_at")
    list_filter = (("sale__branch", admin.RelatedOnlyFieldListFilter),)
    search_fields = ("sale__receipt_no",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "entity", "branch")
    list_filter = ("branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    search_fields = ("action", "entity", "notes")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("po_no", "supplier", "branch", "status", "total", "created_at")
    list_filter = ("status", "branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    search_fields = ("po_no", "supplier")
    inlines = [PurchaseOrderItemInline]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("get_username", "role", "access_level", "company", "branch", "is_active", "created_at")
    list_filter = ("role", "access_level", "is_active", "company", "branch")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("User Info", {
            "fields": ("user",)
        }),
        ("Position & Access", {
            "fields": ("pos_username", "role", "access_level", "pin"),
            "description": "pos_username is the login name within this company (can repeat across companies). Leave PIN blank to disable PIN login.",
        }),
        ("Scope", {
            "fields": ("company", "branch"),
            "description": "Company is auto-filled from branch on save.",
        }),
        ("Status", {
            "fields": ("is_active",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def get_username(self, obj):
        return obj.user.get_full_name() or obj.user.username
    get_username.short_description = "User"

    def save_model(self, request, obj, form, change):
        from django.contrib.auth.hashers import make_password, is_password_usable
        raw_pin = form.cleaned_data.get("pin", "")
        if raw_pin and not is_password_usable(raw_pin):
            # already a hash — don't re-hash
            pass
        elif raw_pin and not raw_pin.startswith(("pbkdf2_", "bcrypt", "argon2")):
            obj.pin = make_password(raw_pin)
        elif not raw_pin:
            if change:
                obj.pin = UserProfile.objects.get(pk=obj.pk).pin  # keep existing
            else:
                obj.pin = ""
        if obj.branch and not obj.company:
            obj.company = obj.branch.company
        super().save_model(request, obj, form, change)


@admin.register(MpesaStkLog)
class MpesaStkLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "phone", "amount", "reference", "success", "merchant_request_id", "checkout_request_id")
    list_filter = ("success", "branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    search_fields = ("phone", "reference", "merchant_request_id", "checkout_request_id")
    readonly_fields = ("sale", "payment", "phone", "amount", "reference", "request", "response", "success", "message", "merchant_request_id", "checkout_request_id", "result_code", "result_desc", "created_at", "updated_at")


@admin.register(MpesaDirectPaymentLog)
class MpesaDirectPaymentLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "branch", "transaction_id", "amount", "success", "conversation_id")
    list_filter = ("success", "branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    search_fields = ("transaction_id", "conversation_id", "originator_conversation_id", "phone", "payer_name")
    readonly_fields = (
        "branch", "sale", "payment", "transaction_id", "amount", "phone", "payer_name",
        "request", "response", "success", "message", "originator_conversation_id",
        "conversation_id", "result_code", "result_desc", "created_at", "updated_at",
    )


@admin.register(StocktakeSession)
class StocktakeAdmin(admin.ModelAdmin):
    list_display = ("session_no", "branch", "status", "created_at", "approved_at")
    list_filter = ("status", "branch", ("branch__company", admin.RelatedOnlyFieldListFilter))
    inlines = [StocktakeItemInline]
