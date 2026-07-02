from rest_framework import serializers

from ..models import Branch, Company, CompanySettings
from ._helpers import _validate_branch_access


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
