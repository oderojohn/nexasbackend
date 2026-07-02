from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import AuditLog, Branch, Product, PurchaseOrder, PurchaseOrderItem, StocktakeItem, StocktakeSession, StockMovement
from ._helpers import _validate_branch_access, _validate_same_branch


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
