from rest_framework import serializers

from ..models import Payment, Product, Sale, SaleReturn, SaleReturnItem, Shift
from ._helpers import _validate_branch_access, _validate_same_branch


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
