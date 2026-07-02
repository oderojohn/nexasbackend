from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import Branch, Customer, HeldOrder, HeldOrderItem, Payment, Product, ReceiptCopy, Register, Sale, SaleItem, Shift
from ._helpers import _validate_branch_access, _validate_same_branch


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
    initiate_stk = serializers.BooleanField(required=False, default=False)
    mpesa_checkout_request_id = serializers.CharField(required=False, allow_blank=True)
    mpesa_direct_transaction_id = serializers.CharField(required=False, allow_blank=True)
    mpesa_manual_approval = serializers.BooleanField(required=False, default=False)
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
