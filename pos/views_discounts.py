"""Discount engine and price scheduler viewsets."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import DiscountRule, DiscountRuleLog, PriceSchedule, PriceScheduleLog, Product
from .views_helpers import _filter_branch_scoped_queryset, _resolve_read_branch


def _snapshot_rule(rule):
    """Return a JSON-serialisable snapshot of a discount rule."""
    return {
        "id": rule.id,
        "name": rule.name,
        "discount_type": rule.discount_type,
        "value": str(rule.value),
        "target": rule.target,
        "category_name": rule.category.name if rule.category_id else None,
        "product_name": rule.product.name if rule.product_id else None,
        "start_date": str(rule.start_date) if rule.start_date else None,
        "end_date": str(rule.end_date) if rule.end_date else None,
        "start_time": str(rule.start_time) if rule.start_time else None,
        "end_time": str(rule.end_time) if rule.end_time else None,
        "days_of_week": rule.days_of_week or [],
        "is_active": rule.is_active,
    }


def _log_rule(rule, action, user):
    DiscountRuleLog.objects.create(
        branch=rule.branch,
        rule=rule,
        action=action,
        rule_name=rule.name,
        rule_snapshot=_snapshot_rule(rule),
        performed_by=user,
    )


def _snapshot_schedule(schedule):
    """Return a JSON-serialisable snapshot of a price schedule."""
    return {
        "id": schedule.id,
        "product_name": schedule.product.name if schedule.product_id else None,
        "product_sku": schedule.product.sku if schedule.product_id else None,
        "new_retail_price": str(schedule.new_retail_price) if schedule.new_retail_price is not None else None,
        "new_wholesale_price": str(schedule.new_wholesale_price) if schedule.new_wholesale_price is not None else None,
        "effective_at": schedule.effective_at.isoformat() if schedule.effective_at else None,
        "is_applied": schedule.is_applied,
        "applied_at": schedule.applied_at.isoformat() if schedule.applied_at else None,
        "note": schedule.note or "",
    }


def _log_schedule(schedule, action, user):
    PriceScheduleLog.objects.create(
        branch=schedule.branch,
        schedule=schedule,
        action=action,
        product_name=schedule.product.name if schedule.product_id else "Unknown",
        schedule_snapshot=_snapshot_schedule(schedule),
        performed_by=user,
    )


# ── Serializers ────────────────────────────────────────────────────────────────

class DiscountRuleLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DiscountRuleLog
        fields = [
            "id", "branch", "rule", "action", "rule_name",
            "rule_snapshot", "performed_by", "performed_by_name", "performed_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        if not obj.performed_by_id:
            return None
        return obj.performed_by.get_full_name() or obj.performed_by.username


class DiscountRuleSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    product_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    is_running = serializers.SerializerMethodField()

    class Meta:
        model = DiscountRule
        fields = [
            'id', 'branch', 'name', 'discount_type', 'value', 'target',
            'category', 'category_name', 'product', 'product_name',
            'start_date', 'end_date', 'days_of_week', 'start_time', 'end_time',
            'is_active', 'is_running', 'created_by', 'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    def get_category_name(self, obj):
        return obj.category.name if obj.category_id else None

    def get_product_name(self, obj):
        return obj.product.name if obj.product_id else None

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return None
        return obj.created_by.get_full_name() or obj.created_by.username

    def get_is_running(self, obj):
        return obj.is_active_now()


class PriceScheduleLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PriceScheduleLog
        fields = [
            "id", "branch", "schedule", "action", "product_name",
            "schedule_snapshot", "performed_by", "performed_by_name", "performed_at",
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        if not obj.performed_by_id:
            return None
        return obj.performed_by.get_full_name() or obj.performed_by.username


class PriceScheduleSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField()
    product_sku = serializers.SerializerMethodField()
    current_retail = serializers.SerializerMethodField()
    current_wholesale = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PriceSchedule
        fields = [
            'id', 'branch', 'product', 'product_name', 'product_sku',
            'current_retail', 'current_wholesale',
            'new_retail_price', 'new_wholesale_price',
            'effective_at', 'applied_at', 'is_applied',
            'note', 'created_by', 'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'applied_at', 'is_applied', 'created_at', 'updated_at', 'created_by']

    def get_product_name(self, obj):
        return obj.product.name if obj.product_id else None

    def get_product_sku(self, obj):
        return obj.product.sku if obj.product_id else None

    def get_current_retail(self, obj):
        return str(obj.product.retail_price) if obj.product_id else None

    def get_current_wholesale(self, obj):
        return str(obj.product.wholesale_price) if obj.product_id else None

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return None
        return obj.created_by.get_full_name() or obj.created_by.username

    def validate(self, data):
        if not data.get('new_retail_price') and not data.get('new_wholesale_price'):
            raise ValidationError("Provide at least one of new_retail_price or new_wholesale_price.")
        return data


# ── ViewSets ──────────────────────────────────────────────────────────────────

class DiscountRuleViewSet(viewsets.ModelViewSet):
    queryset = DiscountRule.objects.select_related('branch', 'category', 'product', 'created_by')
    serializer_class = DiscountRuleSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        branch_id = self.request.query_params.get('branch')
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        active = self.request.query_params.get('is_active')
        if active is not None:
            queryset = queryset.filter(is_active=active.lower() in ('1', 'true', 'yes'))
        return queryset

    def perform_create(self, serializer):
        rule = serializer.save(created_by=self.request.user)
        _log_rule(rule, DiscountRuleLog.CREATED, self.request.user)

    def perform_update(self, serializer):
        old_active = serializer.instance.is_active
        rule = serializer.save()
        # Detect activation / deactivation as a distinct action
        if rule.is_active != old_active:
            action = DiscountRuleLog.ACTIVATED if rule.is_active else DiscountRuleLog.DEACTIVATED
        else:
            action = DiscountRuleLog.UPDATED
        _log_rule(rule, action, self.request.user)

    def perform_destroy(self, instance):
        # Snapshot before deletion so the log record is useful after the rule is gone
        DiscountRuleLog.objects.create(
            branch=instance.branch,
            rule=None,
            action=DiscountRuleLog.DELETED,
            rule_name=instance.name,
            rule_snapshot=_snapshot_rule(instance),
            performed_by=self.request.user,
        )
        instance.delete()

    @action(detail=False, methods=['get'], url_path='active-now')
    def active_now(self, request):
        """Rules currently active — used by POS terminal at checkout time."""
        rules = self.get_queryset().filter(is_active=True)
        active = [r for r in rules if r.is_active_now()]
        return Response(DiscountRuleSerializer(active, many=True).data)

    @action(detail=False, methods=['get'], url_path='logs')
    def logs(self, request):
        """Audit log of all create/update/delete actions on discount rules."""
        from .sales_control import _parse_iso_date
        branch_id = request.query_params.get('branch')
        qs = DiscountRuleLog.objects.select_related('performed_by', 'rule')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        else:
            qs = _filter_branch_scoped_queryset(qs, request)
        date_from = _parse_iso_date(request.query_params.get('date_from'), 'date_from')
        date_to = _parse_iso_date(request.query_params.get('date_to'), 'date_to')
        if date_from:
            qs = qs.filter(performed_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(performed_at__date__lte=date_to)
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(DiscountRuleLogSerializer(page, many=True).data)
        return Response(DiscountRuleLogSerializer(qs, many=True).data)


class PriceScheduleViewSet(viewsets.ModelViewSet):
    queryset = PriceSchedule.objects.select_related('branch', 'product', 'created_by')
    serializer_class = PriceScheduleSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        branch_id = self.request.query_params.get('branch')
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        applied = self.request.query_params.get('is_applied')
        if applied is not None:
            queryset = queryset.filter(is_applied=applied.lower() in ('1', 'true', 'yes'))
        return queryset

    def perform_create(self, serializer):
        schedule = serializer.save(created_by=self.request.user)
        _log_schedule(schedule, PriceScheduleLog.CREATED, self.request.user)

    def perform_update(self, serializer):
        schedule = serializer.save()
        _log_schedule(schedule, PriceScheduleLog.UPDATED, self.request.user)

    def perform_destroy(self, instance):
        PriceScheduleLog.objects.create(
            branch=instance.branch,
            schedule=None,
            action=PriceScheduleLog.DELETED,
            product_name=instance.product.name if instance.product_id else "Unknown",
            schedule_snapshot=_snapshot_schedule(instance),
            performed_by=self.request.user,
        )
        instance.delete()

    @action(detail=True, methods=['post'], url_path='apply')
    def apply_single(self, request, pk=None):
        """Immediately apply a specific price schedule regardless of effective_at."""
        schedule = self.get_object()
        if schedule.is_applied:
            return Response({'detail': 'This schedule has already been applied.'}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        try:
            with transaction.atomic():
                product = schedule.product
                update_fields = []
                if schedule.new_retail_price is not None:
                    product.retail_price = schedule.new_retail_price
                    update_fields.append('retail_price')
                if schedule.new_wholesale_price is not None:
                    product.wholesale_price = schedule.new_wholesale_price
                    update_fields.append('wholesale_price')
                if update_fields:
                    update_fields.append('updated_at')
                    product.save(update_fields=update_fields)
                schedule.is_applied = True
                schedule.applied_at = now
                schedule.save(update_fields=['is_applied', 'applied_at', 'updated_at'])
                _log_schedule(schedule, PriceScheduleLog.APPLIED, request.user)
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(PriceScheduleSerializer(schedule).data)

    @action(detail=False, methods=['post'], url_path='apply-due')
    def apply_due(self, request):
        """Apply all price schedules whose effective_at has passed."""
        now = timezone.now()
        branch_id = request.data.get('branch') or request.query_params.get('branch')
        qs = PriceSchedule.objects.filter(is_applied=False, effective_at__lte=now)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        applied_count = 0
        errors = []
        for schedule in qs.select_related('product', 'branch'):
            try:
                with transaction.atomic():
                    product = schedule.product
                    update_fields = []
                    if schedule.new_retail_price is not None:
                        product.retail_price = schedule.new_retail_price
                        update_fields.append('retail_price')
                    if schedule.new_wholesale_price is not None:
                        product.wholesale_price = schedule.new_wholesale_price
                        update_fields.append('wholesale_price')
                    if update_fields:
                        update_fields.append('updated_at')
                        product.save(update_fields=update_fields)
                    schedule.is_applied = True
                    schedule.applied_at = now
                    schedule.save(update_fields=['is_applied', 'applied_at', 'updated_at'])
                    _log_schedule(schedule, PriceScheduleLog.APPLIED, request.user)
                    applied_count += 1
            except Exception as exc:
                errors.append(f"Schedule {schedule.id}: {exc}")
        return Response({'applied': applied_count, 'errors': errors})

    @action(detail=False, methods=['get'], url_path='logs')
    def logs(self, request):
        """Audit log of all create/update/delete/apply actions on price schedules."""
        from .sales_control import _parse_iso_date
        branch_id = request.query_params.get('branch')
        qs = PriceScheduleLog.objects.select_related('performed_by', 'schedule')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        else:
            qs = _filter_branch_scoped_queryset(qs, request)
        date_from = _parse_iso_date(request.query_params.get('date_from'), 'date_from')
        date_to = _parse_iso_date(request.query_params.get('date_to'), 'date_to')
        if date_from:
            qs = qs.filter(performed_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(performed_at__date__lte=date_to)
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(PriceScheduleLogSerializer(page, many=True).data)
        return Response(PriceScheduleLogSerializer(qs, many=True).data)
