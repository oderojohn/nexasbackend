from rest_framework import serializers

from ..models import Branch, Customer, Supplier
from ._helpers import _validate_branch_access


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"

    def validate(self, attrs):
        branch = attrs.get("branch")
        if self.instance and branch and branch.id != self.instance.branch_id:
            raise serializers.ValidationError({"branch": "Cannot change branch of an existing customer."})
        if branch:
            _validate_branch_access(self.context, branch)
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True
    )

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
