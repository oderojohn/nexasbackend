"""Customer and Supplier viewsets."""
from django.db.models import Q
from rest_framework import viewsets

from .models import Customer, Supplier
from .serializers import CustomerSerializer, SupplierSerializer
from .views_helpers import _filter_branch_scoped_queryset, _resolve_write_branch


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
