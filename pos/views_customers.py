"""Customer and Supplier viewsets."""
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import Customer, CreditRepayment, Sale, Shift, Supplier
from .serializers import CustomerSerializer, SupplierSerializer
from .services import (
    adjust_loyalty_points,
    award_loyalty_points,
    record_credit_repayment,
    redeem_loyalty_points,
)
from .views_helpers import _filter_branch_scoped_queryset, _resolve_read_branch, _resolve_write_branch, is_branch_admin


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.select_related("branch__company")
    serializer_class = CustomerSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(phone__icontains=search) | Q(email__icontains=search)
            )
        return queryset

    def _check_phone_unique(self, branch, phone, exclude_pk=None):
        phone = (phone or "").strip()
        if not phone:
            return
        qs = Customer.objects.filter(branch=branch, phone=phone)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if qs.exists():
            raise ValidationError({"phone": "A customer with this phone number already exists for this branch."})

    def perform_create(self, serializer):
        branch = _resolve_write_branch(self.request)
        self._check_phone_unique(branch, serializer.validated_data.get("phone"))
        serializer.save(branch=branch)

    def perform_update(self, serializer):
        instance = serializer.instance
        branch = serializer.validated_data.get("branch") or instance.branch
        if "phone" in serializer.validated_data:
            self._check_phone_unique(branch, serializer.validated_data.get("phone"), exclude_pk=instance.pk)
        serializer.save()

    @action(detail=False, methods=["get"], url_path="lookup-by-phone")
    def lookup_by_phone(self, request):
        phone = (request.query_params.get("phone") or "").strip()
        if not phone:
            raise ValidationError({"phone": "phone is required."})
        branch = _resolve_read_branch(request)
        if not branch:
            raise NotFound("No customer found with this phone number.")
        customer = Customer.objects.filter(branch=branch, phone=phone, is_active=True).first()
        if not customer:
            raise NotFound("No registered customer found with this phone number.")
        return Response(CustomerSerializer(customer).data)

    @action(detail=True, methods=["get"], url_path="purchase-history")
    def purchase_history(self, request, pk=None):
        customer = self.get_object()
        sales = Sale.objects.filter(customer=customer).order_by("-created_at")[:200]
        rows = [
            {
                "id": sale.id,
                "receipt_no": sale.receipt_no,
                "created_at": sale.created_at,
                "total": sale.total,
                "status": sale.status,
                "methods": list(sale.payments.values_list("method", flat=True)),
            }
            for sale in sales
        ]
        return Response(rows)

    @action(detail=True, methods=["get"], url_path="credit-history")
    def credit_history(self, request, pk=None):
        customer = self.get_object()
        repayments = customer.credit_repayments.select_related("recorded_by").order_by("-created_at")[:200]
        rows = [
            {
                "id": r.id,
                "amount": r.amount,
                "method": r.method,
                "reference": r.reference,
                "recorded_by": r.recorded_by.username if r.recorded_by else "",
                "created_at": r.created_at,
            }
            for r in repayments
        ]
        return Response(rows)

    @action(detail=True, methods=["post"], url_path="settle-credit")
    def settle_credit(self, request, pk=None):
        customer = self.get_object()
        try:
            amount = Decimal(str(request.data.get("amount", "0")))
        except InvalidOperation:
            raise ValidationError({"amount": "Enter a valid amount."})
        method = request.data.get("method") or CreditRepayment.CASH
        if method not in dict(CreditRepayment.METHOD_CHOICES):
            raise ValidationError({"method": "Choose a valid payment method."})
        reference = (request.data.get("reference") or "").strip()
        shift = None
        shift_id = request.data.get("shift")
        if shift_id:
            shift = Shift.objects.filter(pk=shift_id, branch=customer.branch).first()
            if not shift:
                raise ValidationError({"shift": "Shift not found for this branch."})
        repayment = record_credit_repayment(
            customer=customer, amount=amount, recorded_by=request.user,
            method=method, reference=reference, shift=shift,
        )
        customer.refresh_from_db()
        return Response({
            "repayment": {
                "id": repayment.id,
                "amount": repayment.amount,
                "method": repayment.method,
                "reference": repayment.reference,
                "created_at": repayment.created_at,
            },
            "customer": CustomerSerializer(customer).data,
        })

    @action(detail=True, methods=["post"], url_path="award-loyalty-points")
    def award_points(self, request, pk=None):
        customer = self.get_object()
        try:
            sale_amount = Decimal(str(request.data.get("sale_amount", "0")))
        except InvalidOperation:
            raise ValidationError({"sale_amount": "Enter a valid amount."})
        sale = None
        sale_id = request.data.get("sale_id")
        if sale_id:
            sale = Sale.objects.filter(pk=sale_id, branch=customer.branch).first()
        points_earned, balance = award_loyalty_points(
            customer=customer, sale_amount=sale_amount, recorded_by=request.user, branch=customer.branch, sale=sale,
        )
        return Response({"points_earned": points_earned, "loyalty_points": balance})

    @action(detail=True, methods=["post"], url_path="redeem-loyalty-points")
    def redeem_points(self, request, pk=None):
        if not is_branch_admin(request.user):
            raise PermissionDenied("Only branch admins, company admins, or super admins can redeem loyalty points.")
        customer = self.get_object()
        try:
            points = int(request.data.get("points", 0))
        except (TypeError, ValueError):
            raise ValidationError({"points": "Enter a valid whole number of points."})
        value, balance = redeem_loyalty_points(customer=customer, points=points, recorded_by=request.user, branch=customer.branch)
        return Response({"value": value, "loyalty_points": balance})

    @action(detail=True, methods=["post"], url_path="adjust-loyalty-points")
    def adjust_points(self, request, pk=None):
        if not is_branch_admin(request.user):
            raise PermissionDenied("Only branch admins, company admins, or super admins can adjust loyalty points.")
        customer = self.get_object()
        try:
            points_delta = int(request.data.get("points_delta", 0))
        except (TypeError, ValueError):
            raise ValidationError({"points_delta": "Enter a valid whole number."})
        reason = (request.data.get("reason") or "").strip()
        balance = adjust_loyalty_points(customer=customer, points_delta=points_delta, recorded_by=request.user, reason=reason)
        return Response({"loyalty_points": balance})

    @action(detail=False, methods=["get"], url_path="registration-report")
    def registration_report(self, request):
        rows = self.get_queryset().order_by("-created_at").values(
            "id", "name", "phone", "email", "created_at", "is_active", "credit_limit", "loyalty_points",
        )
        return Response(list(rows))


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.select_related("branch__company")
    serializer_class = SupplierSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(phone__icontains=search) | Q(email__icontains=search)
            )
        return queryset

    def _check_name_unique(self, branch, name, exclude_pk=None):
        qs = Supplier.objects.filter(branch=branch, name=name)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if qs.exists():
            raise ValidationError({"name": "A supplier with this name already exists for this branch."})

    def perform_create(self, serializer):
        branch = _resolve_write_branch(self.request)
        self._check_name_unique(branch, serializer.validated_data.get("name"))
        serializer.save(branch=branch)

    def perform_update(self, serializer):
        instance = serializer.instance
        branch = serializer.validated_data.get("branch") or instance.branch
        if "name" in serializer.validated_data:
            self._check_name_unique(branch, serializer.validated_data.get("name"), exclude_pk=instance.pk)
        serializer.save()
