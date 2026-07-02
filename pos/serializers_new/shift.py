from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import Branch, CashTransaction, Register, Shift
from ..permissions import get_pos_profile
from ._helpers import _request_user, _validate_branch_access, _validate_same_branch


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
