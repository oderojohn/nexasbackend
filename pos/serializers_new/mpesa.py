from rest_framework import serializers

from ..models import Branch, MpesaDirectPaymentLog, MpesaStkLog
from ._helpers import _validate_branch_access


class MpesaStkPushSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False, allow_null=True)
    branch_name = serializers.CharField(required=False, allow_blank=True)

    def validate_phone(self, value):
        from ..utils.mpesa import validate_phone
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
