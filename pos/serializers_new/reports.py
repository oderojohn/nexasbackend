from rest_framework import serializers

from ..models import ReportSchedule


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
