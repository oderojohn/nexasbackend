"""Customer and Supplier viewsets."""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import AuditLog, Customer, Supplier
from .serializers import CustomerSerializer, SupplierSerializer
from .views_helpers import _filter_branch_scoped_queryset, _resolve_write_branch, is_branch_admin


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

    def perform_create(self, serializer):
        serializer.save(branch=_resolve_write_branch(self.request))

    @action(detail=True, methods=["post"], url_path="settle-credit")
    @transaction.atomic
    def settle_credit(self, request, pk=None):
        if not is_branch_admin(request.user):
            raise PermissionDenied("Only branch admins, company admins, or super admins can record credit repayments.")

        customer = Customer.objects.select_for_update().get(pk=self.get_object().pk)
        try:
            amount = Decimal(str(request.data.get("amount", "0")))
        except InvalidOperation:
            raise ValidationError({"amount": "Enter a valid amount."})
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than zero."})
        if amount > customer.credit_balance:
            raise ValidationError({"amount": "Amount cannot exceed the outstanding balance."})

        customer.credit_balance -= amount
        customer.save(update_fields=["credit_balance", "updated_at"])
        AuditLog.objects.create(
            user=request.user,
            action="customer.settle_credit",
            entity="Customer",
            entity_id=str(customer.id),
            branch=customer.branch,
            notes=f"Recorded repayment of {amount} for {customer.name}",
        )
        return Response(CustomerSerializer(customer).data)


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

    def perform_create(self, serializer):
        serializer.save(branch=_resolve_write_branch(self.request))
