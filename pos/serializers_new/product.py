from rest_framework import serializers

from ..models import Branch, Category, InventoryStock, Product
from ._helpers import _validate_branch_access, _validate_same_branch


class CategorySerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True
    )

    class Meta:
        model = Category
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        branch_id = self.context.get('branch_id')
        if branch_id:
            self.fields['branch'].queryset = Branch.objects.filter(pk=branch_id, is_active=True)

    def validate(self, attrs):
        branch = attrs.get('branch')
        if not branch:
            branch_id = self.context.get('branch_id')
            if branch_id:
                try:
                    branch = Branch.objects.get(pk=branch_id, is_active=True)
                except Branch.DoesNotExist:
                    pass

        if branch and hasattr(self.instance, 'branch') and self.instance and self.instance.pk:
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        branch_id = self.context.get("branch_id")
        if branch_id:
            self.fields["category"].queryset = Category.objects.filter(branch_id=branch_id, is_active=True)

    def get_stock(self, product):
        branch_id = self.context.get("branch_id")
        rows = product.stock_rows.all()
        if branch_id:
            bid = int(branch_id)
            return sum(row.quantity for row in rows if row.branch_id == bid)
        return sum(row.quantity for row in rows)

    def validate_category(self, value):
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
