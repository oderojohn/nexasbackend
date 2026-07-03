from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import (
    AuditLog,
    Branch,
    CashTransaction,
    Category,
    Company,
    CompanySettings,
    Customer,
    HeldOrder,
    HeldOrderItem,
    InventoryStock,
    Payment,
    PermissionGroup,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceiptCopy,
    Register,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    Shift,
    StocktakeItem,
    StocktakeSession,
    StockMovement,
    Supplier,
    UserProfile,
    MpesaDirectPaymentLog,
    MpesaStkLog,
    ReportSchedule,
)
from .permissions import get_pos_profile, is_super_admin, profile_company, user_can_access_branch
from .rbac import ALL_PERMISSION_CODES, permissions_for_profile


def _request_user(context):
    request = context.get("request") if context else None
    return request.user if request else None


def _validate_branch_access(context, branch):
    user = _request_user(context)
    if user and user.is_authenticated and user_can_access_branch(user, branch):
        return branch
    raise serializers.ValidationError({"branch": "You do not have access to this branch."})


def _validate_same_branch(value, branch, field_name):
    if value and branch and value.branch_id != branch.id:
        raise serializers.ValidationError({field_name: "Must belong to the selected branch."})


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = "__all__"


class BranchSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    mpesa_enabled = serializers.SerializerMethodField()
    mpesa_direct_enabled = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = (
            "id", "company", "company_name", "code", "name", "location", "is_active",
            "mpesa_stk_enabled", "mpesa_manual_approval_enabled", "mpesa_till_enabled",
            "mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_business_shortcode",
            "mpesa_passkey", "mpesa_environment", "mpesa_callback_url", "mpesa_enabled",
            "mpesa_till_number", "mpesa_initiator_name", "mpesa_security_credential",
            "mpesa_direct_result_url", "mpesa_direct_timeout_url", "mpesa_direct_enabled",
            "loyalty_enabled", "loyalty_points_rate", "credit_sale_enabled", "whatsapp_sms_receipt_enabled",
            "created_at", "updated_at",
        )
        extra_kwargs = {
            "mpesa_consumer_key": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_consumer_secret": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_business_shortcode": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_passkey": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_callback_url": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_till_number": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_initiator_name": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_security_credential": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_direct_result_url": {"write_only": True, "required": False, "allow_blank": True},
            "mpesa_direct_timeout_url": {"write_only": True, "required": False, "allow_blank": True},
        }

    def _value(self, attrs, field):
        if field in attrs:
            return attrs.get(field)
        if self.instance is not None:
            return getattr(self.instance, field)
        return ""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        stk_enabled = attrs.get(
            "mpesa_stk_enabled",
            self.instance.mpesa_stk_enabled if self.instance is not None else False,
        )
        till_enabled = attrs.get(
            "mpesa_till_enabled",
            self.instance.mpesa_till_enabled if self.instance is not None else False,
        )
        errors = {}
        if stk_enabled:
            missing = [
                field for field in (
                    "mpesa_consumer_key",
                    "mpesa_consumer_secret",
                    "mpesa_business_shortcode",
                    "mpesa_passkey",
                    "mpesa_callback_url",
                )
                if not self._value(attrs, field)
            ]
            if missing:
                errors["mpesa_stk_enabled"] = f"STK requires: {', '.join(missing)}."
        if till_enabled:
            missing = [
                field for field in (
                    "mpesa_consumer_key",
                    "mpesa_consumer_secret",
                    "mpesa_till_number",
                    "mpesa_initiator_name",
                    "mpesa_security_credential",
                    "mpesa_direct_result_url",
                    "mpesa_direct_timeout_url",
                )
                if not self._value(attrs, field)
            ]
            if missing:
                errors["mpesa_till_enabled"] = f"Till verification requires: {', '.join(missing)}."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def get_mpesa_enabled(self, branch):
        return bool(
            branch.mpesa_stk_enabled
            and branch.mpesa_consumer_key
            and branch.mpesa_consumer_secret
            and branch.mpesa_business_shortcode
            and branch.mpesa_passkey
            and branch.mpesa_callback_url
        )

    def get_mpesa_direct_enabled(self, branch):
        return bool(
            branch.mpesa_till_enabled
            and branch.mpesa_consumer_key
            and branch.mpesa_consumer_secret
            and branch.mpesa_till_number
            and branch.mpesa_initiator_name
            and branch.mpesa_security_credential
            and branch.mpesa_direct_result_url
            and branch.mpesa_direct_timeout_url
        )


class PermissionGroupSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = PermissionGroup
        fields = ['id', 'company', 'name', 'description', 'permissions', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_member_count(self, obj):
        return obj.members.count()

    def validate_permissions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of permission codes.")
        invalid = sorted(set(value) - set(ALL_PERMISSION_CODES))
        if invalid:
            raise serializers.ValidationError(f"Unknown permission codes: {', '.join(invalid)}")
        return value


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username")
    first_name = serializers.CharField(source="user.first_name", required=False, allow_blank=True)
    last_name = serializers.CharField(source="user.last_name", required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    full_name = serializers.CharField(source="user.get_full_name", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    effective_permissions = serializers.SerializerMethodField()
    permission_groups = serializers.PrimaryKeyRelatedField(
        many=True, queryset=PermissionGroup.objects.all(), required=False
    )

    class Meta:
        model = UserProfile
        fields = (
            "id", "user", "username", "first_name", "last_name", "email", "full_name",
            "last_login", "password", "pin", "pos_username", "role", "access_level",
            "branch", "company", "custom_permissions", "use_custom_permissions",
            "permission_groups", "effective_permissions", "is_active", "created_at", "updated_at"
        )
        extra_kwargs = {
            "user": {"required": False},
            "pin": {"write_only": True, "required": False, "allow_blank": True},
            "pos_username": {"required": False, "allow_blank": True},
        }

    def get_effective_permissions(self, profile):
        perms = permissions_for_profile(profile)
        if profile.user.is_superuser or "*" in perms:
            return ALL_PERMISSION_CODES
        return perms

    def validate(self, attrs):
        branch = attrs.get("branch")
        company = attrs.get("company")
        if self.instance is None:
            required = {}
            if not attrs.get("role"):
                required["role"] = "Role is required when creating a user."
            if not attrs.get("access_level"):
                required["access_level"] = "Access level is required when creating a user."
            if not branch:
                required["branch"] = "Branch is required when creating a user."
            if required:
                raise serializers.ValidationError(required)
        if branch and company and branch.company_id != company.id:
            raise serializers.ValidationError({"branch": "Branch must belong to the selected company."})

        # Validate pos_username uniqueness per company
        pos_username = attrs.get("pos_username", "")
        if pos_username:
            resolved_company = company or (branch.company if branch else None)
            if resolved_company:
                qs = UserProfile.objects.filter(company=resolved_company, pos_username=pos_username)
                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError({"pos_username": "This username is already taken in this company."})

        user = _request_user(self.context)
        if not user or not user.is_authenticated:
            return attrs
        if branch and not user_can_access_branch(user, branch):
            raise serializers.ValidationError({"branch": "You do not have access to this branch."})
        if company and not is_super_admin(user):
            active_company = profile_company(get_pos_profile(user))
            if not active_company or company.id != active_company.id:
                raise serializers.ValidationError({"company": "You do not have access to this company."})
        custom_permissions = attrs.get("custom_permissions")
        if custom_permissions is not None:
            if not isinstance(custom_permissions, list):
                raise serializers.ValidationError({"custom_permissions": "Must be a list of permission codes."})
            invalid = sorted(set(custom_permissions) - set(ALL_PERMISSION_CODES))
            if invalid:
                raise serializers.ValidationError({"custom_permissions": f"Unknown permission codes: {', '.join(invalid)}"})
        return attrs

    def create(self, validated_data):
        from django.contrib.auth.hashers import make_password as _hash
        user_data = validated_data.pop("user", {})
        password = validated_data.pop("password", "")
        permission_groups_list = validated_data.pop("permission_groups", [])
        pin = validated_data.get("pin", "")
        if pin:
            validated_data["pin"] = _hash(pin)

        branch = validated_data.get("branch")
        if branch and not validated_data.get("company"):
            validated_data["company"] = branch.company
        company = validated_data.get("company")

        pos_username = validated_data.get("pos_username", "")
        display_username = user_data.get("username", "")

        if not display_username and not pos_username:
            raise serializers.ValidationError({"username": "Username is required."})

        user_model = get_user_model()

        # Auto-generate a globally unique Django username when only pos_username is set.
        if pos_username and company:
            django_username = f"co{company.id}_{pos_username}"[:150]
            if not display_username:
                user_data["username"] = django_username
        else:
            # Legacy path: Django username IS the display username.
            django_username = display_username
            if pos_username == "" and display_username:
                validated_data["pos_username"] = display_username

        if user_model.objects.filter(username=user_data.get("username", django_username)).exists():
            raise serializers.ValidationError({"username": "A user with this username already exists."})

        user = user_model(**user_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.is_active = validated_data.get("is_active", True)
        user.save()

        profile = UserProfile.objects.create(user=user, **validated_data)
        if permission_groups_list:
            profile.permission_groups.set(permission_groups_list)
        return profile

    def update(self, instance, validated_data):
        from django.contrib.auth.hashers import make_password as _hash
        user_data = validated_data.pop("user", None)
        password = validated_data.pop("password", None)
        permission_groups_list = validated_data.pop("permission_groups", None)
        pin = validated_data.get("pin", "")
        if pin:
            validated_data["pin"] = _hash(pin)
        elif "pin" in validated_data:
            # Empty pin in update = keep existing pin unchanged
            validated_data.pop("pin")

        if user_data:
            username = user_data.get("username")
            if username and username != instance.user.username:
                user_model = get_user_model()
                if user_model.objects.filter(username=username).exclude(pk=instance.user_id).exists():
                    raise serializers.ValidationError({"username": "A user with this username already exists."})
            for field, value in user_data.items():
                setattr(instance.user, field, value)

        if password:
            instance.user.set_password(password)

        if user_data or password:
            instance.user.save()

        branch = validated_data.get("branch", instance.branch)
        if branch:
            validated_data["company"] = branch.company
        if "is_active" in validated_data:
            instance.user.is_active = validated_data["is_active"]
            instance.user.save(update_fields=["is_active"])

        instance = super().update(instance, validated_data)
        if permission_groups_list is not None:
            instance.permission_groups.set(permission_groups_list)
        return instance


class CompanySettingsSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = CompanySettings
        fields = (
            "id", "company", "company_name",
            "security", "system", "pos_operations", "stock_controls",
            "notifications", "financial", "pricing", "backup",
            "integrations", "super_admin", "email_config", "cloud_config",
            "created_at", "updated_at",
        )
        read_only_fields = ("company", "created_at", "updated_at")


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    pin = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    company_code = serializers.CharField(required=False, allow_blank=True)


class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Register
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing register."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs


class CategorySerializer(serializers.ModelSerializer):
    # Optional: allow omitting branch on creation; server resolves from active context/branch
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)


    # Allow omitting branch on creation; server will resolve from context/active branch
    
    
    class Meta:
        model = Category
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter queryset based on branch context if provided
        branch_id = self.context.get('branch_id')
        if branch_id:
            self.fields['branch'].queryset = Branch.objects.filter(pk=branch_id, is_active=True)
            # Also filter the queryset for listing to only show categories from this branch
            if hasattr(self.Meta, 'queryset') and self.Meta.queryset is not None:
                self.Meta.queryset = self.Meta.queryset.filter(branch_id=branch_id)

    def validate(self, attrs):
        # When creating/updating a category, ensure it belongs to the correct branch
        branch = attrs.get('branch')
        if not branch:
            # Try to get branch from context if not provided in attrs
            branch_id = self.context.get('branch_id')
            if branch_id:
                try:
                    branch = Branch.objects.get(pk=branch_id, is_active=True)
                except Branch.DoesNotExist:
                    pass
        
        if branch and hasattr(self.instance, 'branch') and self.instance.pk:
            # For updates, ensure branch hasn't changed
            if branch != self.instance.branch:
                raise serializers.ValidationError({"branch": "Cannot change branch of an existing category."})
        elif branch:
            _validate_branch_access(self.context, branch)
        return attrs


class CategoryPKField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if isinstance(data, str) and data.isdigit():
            data = int(data)
        if isinstance(data, str):
            branch_id = self.context.get("branch_id")
            queryset = self.get_queryset()
            if branch_id:
                queryset = queryset.filter(branch_id=branch_id)
            match = queryset.filter(name=data).first()
            if match:
                return match
            raise serializers.ValidationError(f'Invalid pk "{data}" - object does not exist.')
        return super().to_internal_value(data)


class ProductSerializer(serializers.ModelSerializer):
    stock = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    company = serializers.IntegerField(source="branch.company_id", read_only=True)
    category = CategoryPKField(queryset=Category.objects.all())

    class Meta:
        model = Product
        fields = "__all__"

    def get_stock(self, product):
        branch_id = self.context.get("branch_id")
        # Use the prefetch cache — filtering with .filter() bypasses it and fires N extra queries
        rows = product.stock_rows.all()
        if branch_id:
            bid = int(branch_id)
            return sum(row.quantity for row in rows if row.branch_id == bid)
        return sum(row.quantity for row in rows)

    def validate_category(self, value):
        # When creating/updating a product, ensure the category belongs to the same branch
        branch_id = self.context.get("branch_id")
        if branch_id and value.branch_id != int(branch_id):
            raise serializers.ValidationError("Category must belong to the same branch as the product.")
        return value

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing product."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter category choices based on branch context
        branch_id = self.context.get("branch_id")
        if branch_id:
            self.fields["category"].queryset = Category.objects.filter(branch_id=branch_id, is_active=True)


class InventoryStockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = InventoryStock
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        product = attrs.get("product")
        if self.instance:
            if branch and branch.id != self.instance.branch_id:
                raise serializers.ValidationError({"branch": "Cannot change branch of an existing stock row."})
            branch = branch or self.instance.branch
            product = product or self.instance.product
        if branch:
            _validate_branch_access(self.context, branch)
        _validate_same_branch(product, branch, "product")
        return attrs


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"
        read_only_fields = ("credit_balance", "loyalty_points")

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing customer."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)

    class Meta:
        model = Supplier
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing supplier."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs


class ShiftSerializer(serializers.ModelSerializer):
    cashier_name = serializers.CharField(source="cashier.get_username", read_only=True)

    class Meta:
        model = Shift
        fields = "__all__"
        read_only_fields = ("expected_cash", "cash_variance", "closed_at", "status")

    def validate(self, attrs):
        branch = attrs.get("branch")
        register = attrs.get("register")
        if self.instance:
            if branch and branch.id != self.instance.branch_id:
                raise serializers.ValidationError({"branch": "Cannot change branch of an existing shift."})
            branch = branch or self.instance.branch
            register = register or self.instance.register
        if branch:
            _validate_branch_access(self.context, branch)
        _validate_same_branch(register, branch, "register")
        return attrs


class OpenShiftSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    register = serializers.PrimaryKeyRelatedField(queryset=Register.objects.filter(is_active=True))
    cashier = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all())
    opening_cash = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)

    def validate(self, attrs):
        branch = attrs["branch"]
        _validate_branch_access(self.context, branch)
        _validate_same_branch(attrs["register"], branch, "register")
        profile = get_pos_profile(attrs["cashier"])
        if profile and profile.branch_id and profile.branch_id != branch.id:
            raise serializers.ValidationError({"cashier": "Cashier must belong to the selected branch."})
        return attrs


class CloseShiftSerializer(serializers.Serializer):
    counted_cash = serializers.DecimalField(max_digits=12, decimal_places=2)


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SaleItem
        fields = "__all__"


class PaymentSerializer(serializers.ModelSerializer):
    receipt_no = serializers.CharField(source="sale.receipt_no", read_only=True)
    sale_id = serializers.IntegerField(source="sale.id", read_only=True)
    sale_status = serializers.CharField(source="sale.status", read_only=True)
    customer_name = serializers.CharField(source="sale.customer.name", read_only=True)
    cashier_name = serializers.CharField(source="sale.cashier.username", read_only=True)

    class Meta:
        model = Payment
        fields = "__all__"


class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    cashier_name = serializers.CharField(source="cashier.get_username", read_only=True)
    voided_by_name = serializers.CharField(source="voided_by.get_username", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    register_code = serializers.CharField(source="register.code", read_only=True)

    class Meta:
        model = Sale
        fields = "__all__"


class CheckoutItemSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)


class CheckoutPaymentSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Payment.METHOD_CHOICES)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference = serializers.CharField(required=False, allow_blank=True)


class CheckoutSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    register = serializers.PrimaryKeyRelatedField(queryset=Register.objects.filter(is_active=True))
    shift = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.filter(status=Shift.OPEN))
    cashier = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all())
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True)
    mode = serializers.ChoiceField(choices=Sale.MODE_CHOICES, default=Sale.RETAIL)
    items = CheckoutItemSerializer(many=True)
    payments = CheckoutPaymentSerializer(many=True)
    # Kept for older clients; new POS flow sends STK first, waits for callback success,
    # then submits checkout with mpesa_checkout_request_id.
    initiate_stk = serializers.BooleanField(required=False, default=False)
    mpesa_checkout_request_id = serializers.CharField(required=False, allow_blank=True)
    mpesa_direct_transaction_id = serializers.CharField(required=False, allow_blank=True)
    mpesa_manual_approval = serializers.BooleanField(required=False, default=False)
    # Offline-sync fields — sent by desktop POS when re-uploading locally-created sales
    device_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    receipt_no = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def validate(self, attrs):
        branch = attrs["branch"]
        _validate_branch_access(self.context, branch)
        _validate_same_branch(attrs["register"], branch, "register")
        _validate_same_branch(attrs["shift"], branch, "shift")
        if attrs["shift"].register_id != attrs["register"].id:
            raise serializers.ValidationError({"shift": "Shift must belong to the selected register."})
        customer = attrs.get("customer")
        _validate_same_branch(customer, branch, "customer")
        for item in attrs.get("items", []):
            _validate_same_branch(item["product"], branch, "items")
        return attrs


class VoidSaleSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=240)


class ReprintReceiptSerializer(serializers.Serializer):
    pass


class SaleReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SaleReturnItem
        fields = "__all__"


class SaleReturnSerializer(serializers.ModelSerializer):
    items = SaleReturnItemSerializer(many=True, read_only=True)
    sale_receipt_no = serializers.CharField(source="sale.receipt_no", read_only=True)
    processed_by_name = serializers.CharField(source="processed_by.username", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.username", read_only=True)

    class Meta:
        model = SaleReturn
        fields = "__all__"


class CreateSaleReturnItemSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)


class CreateSaleReturnSerializer(serializers.Serializer):
    sale = serializers.PrimaryKeyRelatedField(queryset=Sale.objects.filter(status=Sale.PAID))
    reason = serializers.CharField(max_length=240)
    refund_method = serializers.ChoiceField(choices=Payment.METHOD_CHOICES, default=Payment.CASH)
    shift = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.filter(status=Shift.OPEN), required=False, allow_null=True)
    items = CreateSaleReturnItemSerializer(many=True)

    def validate(self, attrs):
        sale = attrs["sale"]
        branch = sale.branch
        _validate_branch_access(self.context, branch)
        shift = attrs.get("shift")
        if shift and shift.branch_id != branch.id:
            raise serializers.ValidationError({"shift": "Shift must belong to the sale branch."})
        for item in attrs.get("items", []):
            _validate_same_branch(item["product"], branch, "items")
        return attrs


class ApproveSaleReturnSerializer(serializers.Serializer):
    pass


class RejectSaleReturnSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True)


class CompleteSaleReturnSerializer(serializers.Serializer):
    pass


class CashTransactionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = CashTransaction
        fields = "__all__"


class CreateCashTransactionSerializer(serializers.Serializer):
    shift = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.filter(status=Shift.OPEN))
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    transaction_type = serializers.ChoiceField(choices=CashTransaction.TYPE_CHOICES)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    user = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False, allow_null=True)

    def validate(self, attrs):
        branch = attrs["branch"]
        _validate_branch_access(self.context, branch)
        _validate_same_branch(attrs["shift"], branch, "shift")
        if not attrs.get("user"):
            attrs["user"] = _request_user(self.context)
        return attrs


class ReceiptCopySerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptCopy
        fields = "__all__"


class HeldOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = HeldOrderItem
        fields = "__all__"


class HeldOrderSerializer(serializers.ModelSerializer):
    items = HeldOrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = HeldOrder
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        register = attrs.get("register")
        customer = attrs.get("customer")
        if self.instance:
            if branch and branch.id != self.instance.branch_id:
                raise serializers.ValidationError({"branch": "Cannot change branch of an existing held order."})
            branch = branch or self.instance.branch
            register = register or self.instance.register
            customer = customer or self.instance.customer
        if branch:
            _validate_branch_access(self.context, branch)
        _validate_same_branch(register, branch, "register")
        _validate_same_branch(customer, branch, "customer")
        return attrs


class HoldOrderItemInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)


class HoldOrderSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    register = serializers.PrimaryKeyRelatedField(queryset=Register.objects.filter(is_active=True))
    cashier = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all())
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)
    items = HoldOrderItemInputSerializer(many=True)

    def validate(self, attrs):
        branch = attrs["branch"]
        _validate_branch_access(self.context, branch)
        _validate_same_branch(attrs["register"], branch, "register")
        customer = attrs.get("customer")
        _validate_same_branch(customer, branch, "customer")
        for item in attrs.get("items", []):
            _validate_same_branch(item["product"], branch, "items")
        return attrs


class UpdateHoldOrderSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True
    )
    note = serializers.CharField(required=False, allow_blank=True)
    items = HoldOrderItemInputSerializer(many=True, required=False)

    def validate(self, attrs):
        held_order = self.context.get("held_order")
        if not held_order:
            return attrs
        branch = held_order.branch
        customer = attrs.get("customer")
        _validate_same_branch(customer, branch, "customer")
        for item in attrs.get("items", []):
            _validate_same_branch(item["product"], branch, "items")
        return attrs

    def validate_items(self, value):
        if value is not None and not value:
            raise serializers.ValidationError("At least one item is required.")
        held_order = self.context.get("held_order")
        if held_order and value is not None:
            submitted_quantities = {}
            for item in value:
                product_id = item["product"].id
                submitted_quantities[product_id] = submitted_quantities.get(product_id, 0) + item["quantity"]
            for held_item in held_order.items.select_related("product").all():
                submitted_qty = submitted_quantities.get(held_item.product_id, 0)
                if submitted_qty < held_item.quantity:
                    raise serializers.ValidationError(
                        f"Cannot remove or reduce {held_item.product.name} from a loaded held order."
                    )
        return value


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    user_display = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    def get_user_display(self, obj):
        if not obj.user_id:
            return "System"
        u = obj.user
        return u.get_full_name() or u.username

    class Meta:
        model = StockMovement
        fields = "__all__"


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AuditLog
        fields = "__all__"


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = "__all__"


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing purchase order."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs


class PurchaseOrderItemInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    ordered_quantity = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)

    def validate_product(self, product):
        if not product.is_active:
            raise serializers.ValidationError(f"{product.name} is inactive and cannot be added to a purchase order.")
        return product


class CreatePurchaseOrderSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    supplier = serializers.CharField(max_length=160)
    created_by = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False, allow_null=True)
    expected_at = serializers.DateField(required=False, allow_null=True)
    items = PurchaseOrderItemInputSerializer(many=True)

    def validate(self, attrs):
        branch = attrs["branch"]
        _validate_branch_access(self.context, branch)
        for item in attrs.get("items", []):
            _validate_same_branch(item["product"], branch, "items")
        return attrs


class UpdatePurchaseOrderSerializer(serializers.Serializer):
    supplier = serializers.CharField(max_length=160)
    expected_at = serializers.DateField(required=False, allow_null=True)
    items = PurchaseOrderItemInputSerializer(many=True)

    def validate(self, attrs):
        for item in attrs.get("items", []):
            po = self.instance
            if item["product"].branch_id != po.branch_id:
                raise serializers.ValidationError({"items": f"{item['product'].name} does not belong to the PO's branch."})
        return attrs


class ReceiveItemSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrderItem.objects.select_related("purchase_order", "product"))
    received_quantity = serializers.IntegerField(min_value=0)


class ReceivePurchaseOrderSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False, allow_null=True)
    items = ReceiveItemSerializer(many=True)


class StockAdjustmentSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity_delta = serializers.IntegerField()
    reason = serializers.CharField(max_length=120)
    user = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False, allow_null=True)

    def validate(self, attrs):
        branch = attrs["branch"]
        _validate_branch_access(self.context, branch)
        _validate_same_branch(attrs["product"], branch, "product")
        return attrs


class StocktakeItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    variance = serializers.IntegerField(read_only=True)

    class Meta:
        model = StocktakeItem
        fields = "__all__"


class StocktakeSessionSerializer(serializers.ModelSerializer):
    items = StocktakeItemSerializer(many=True, read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return None
        u = obj.created_by
        return u.get_full_name() or u.username

    def get_approved_by_name(self, obj):
        if not obj.approved_by_id:
            return None
        u = obj.approved_by
        return u.get_full_name() or u.username

    class Meta:
        model = StocktakeSession
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing stocktake."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs


class CreateStocktakeSerializer(serializers.Serializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    created_by = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        _validate_branch_access(self.context, attrs["branch"])
        return attrs


class CountStocktakeItemSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=StocktakeItem.objects.select_related("stocktake", "product"))
    counted_quantity = serializers.IntegerField(min_value=0)


class CountStocktakeSerializer(serializers.Serializer):
    items = CountStocktakeItemSerializer(many=True)


class ApproveStocktakeSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all(), required=False, allow_null=True)


class SwitchBranchSerializer(serializers.Serializer):
    """
    Body for POST /auth/switch-branch/

    Admins post the ID of the branch they want to switch into.
    The view validates that the branch belongs to the admin's company
    (superusers can jump to any branch).
    """
    branch = serializers.IntegerField()


class MpesaStkPushSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)
    branch_name = serializers.CharField(required=False, allow_blank=True)

    def validate_phone(self, value):
        from .utils.mpesa import validate_phone
        if not validate_phone(value):
            raise serializers.ValidationError("Invalid phone number format. Use format like 254712345678.")
        return value

    def validate_amount(self, value):
        if value != value.to_integral_value():
            raise serializers.ValidationError("STK amount must be a whole number.")
        return value

    def validate(self, attrs):
        branch = attrs.get('branch')
        if branch is None:
            raise serializers.ValidationError({"branch": "Branch is required for M-Pesa STK."})
        _validate_branch_access(self.context, branch)
        return attrs


class MpesaStkQuerySerializer(serializers.Serializer):
    checkout_request_id = serializers.CharField(max_length=255)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)

    def validate(self, attrs):
        branch = attrs.get('branch')
        if branch is None:
            raise serializers.ValidationError({"branch": "Branch is required for M-Pesa STK query."})
        _validate_branch_access(self.context, branch)
        return attrs


class MpesaDirectLookupSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(max_length=120)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)

    def validate_transaction_id(self, value):
        value = (value or '').strip().upper()
        if not value:
            raise serializers.ValidationError("M-Pesa transaction code is required.")
        return value

    def validate(self, attrs):
        branch = attrs.get('branch')
        if branch is None:
            raise serializers.ValidationError({"branch": "Branch is required for direct till lookup."})
        _validate_branch_access(self.context, branch)
        return attrs


class MpesaStkLogSerializer(serializers.ModelSerializer):
    sale_receipt = serializers.CharField(source='sale.receipt_no', read_only=True)
    payment_reference = serializers.CharField(source='payment.reference', read_only=True)

    class Meta:
        model = MpesaStkLog
        fields = (
            'id', 'branch', 'sale', 'sale_receipt', 'payment', 'payment_reference', 'phone', 'amount', 'reference',
            'request', 'response', 'success', 'message', 'merchant_request_id', 'checkout_request_id',
            'result_code', 'result_desc', 'created_at',
        )
        read_only_fields = ('request', 'response', 'success', 'message', 'merchant_request_id', 'checkout_request_id', 'result_code', 'result_desc', 'created_at')


class MpesaDirectPaymentLogSerializer(serializers.ModelSerializer):
    sale_receipt = serializers.CharField(source='sale.receipt_no', read_only=True)
    payment_reference = serializers.CharField(source='payment.reference', read_only=True)

    class Meta:
        model = MpesaDirectPaymentLog
        fields = (
            'id', 'branch', 'sale', 'sale_receipt', 'payment', 'payment_reference',
            'transaction_id', 'amount', 'phone', 'payer_name', 'request', 'response',
            'success', 'message', 'originator_conversation_id', 'conversation_id',
            'result_code', 'result_desc', 'created_at',
        )
        read_only_fields = (
            'request', 'response', 'success', 'message', 'originator_conversation_id',
            'conversation_id', 'result_code', 'result_desc', 'created_at',
        )


class ReportScheduleSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    last_sent_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ReportSchedule
        fields = (
            'id', 'branch', 'branch_name', 'report_type', 'is_enabled',
            'send_hour', 'send_minute', 'send_day_of_week', 'send_day_of_month',
            'recipients', 'include_gross_profit', 'include_cashier_breakdown',
            'include_payment_methods', 'include_top_products', 'include_returns',
            'last_sent_at', 'created_at', 'updated_at',
        )
        read_only_fields = ('last_sent_at', 'created_at', 'updated_at')

    def validate_recipients(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Recipients must be a list of email addresses.")
        for email in value:
            serializers.EmailField().run_validation(email)
        return value

    def validate_send_hour(self, value):
        if not 0 <= value <= 23:
            raise serializers.ValidationError("Hour must be 0-23.")
        return value

    def validate_send_minute(self, value):
        if not 0 <= value <= 59:
            raise serializers.ValidationError("Minute must be 0-59.")
        return value

    def validate_send_day_of_month(self, value):
        if value is not None and not 1 <= value <= 31:
            raise serializers.ValidationError("Day of month must be 1-31.")
        return value

