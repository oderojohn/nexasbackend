"""Purchase Order and Audit Log viewsets."""
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import AuditLog, PurchaseOrder
from .serializers import (
    AuditLogSerializer,
    CreatePurchaseOrderSerializer,
    PurchaseOrderSerializer,
    ReceivePurchaseOrderSerializer,
    UpdatePurchaseOrderSerializer,
)
from .services import (
    cancel_purchase_order,
    create_purchase_order,
    receive_purchase_order,
    update_purchase_order,
)
from .views_helpers import (
    _filter_branch_scoped_queryset,
    _positive_int_query_param,
    _resolve_read_branch,
)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = (
        PurchaseOrder.objects
        .select_related("branch__company", "created_by")
        .prefetch_related("items__product")
    )
    serializer_class = PurchaseOrderSerializer

    _EDITABLE_STATUSES = {PurchaseOrder.DRAFT, PurchaseOrder.ORDERED}

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        status_value = self.request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @action(detail=False, methods=["post"])
    def create_order(self, request):
        serializer = CreatePurchaseOrderSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        po = create_purchase_order(**serializer.validated_data)
        return Response(PurchaseOrderSerializer(po).data, status=201)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        serializer = ReceivePurchaseOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        po = receive_purchase_order(purchase_order=self.get_object(), **serializer.validated_data)
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        po = self.get_object()
        if po.status in [PurchaseOrder.RECEIVED, PurchaseOrder.PARTIAL]:
            raise ValidationError({"purchase_order": "Received or partially-received orders cannot be cancelled."})
        cancelled_po = cancel_purchase_order(purchase_order=po, user=request.user)
        return Response(PurchaseOrderSerializer(cancelled_po).data)

    @action(detail=True, methods=["post"])
    def update_order(self, request, pk=None):
        serializer = UpdatePurchaseOrderSerializer(
            data=request.data, instance=self.get_object(), context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        po = update_purchase_order(purchase_order=self.get_object(), **serializer.validated_data, user=request.user)
        return Response(PurchaseOrderSerializer(po).data)

    def perform_update(self, serializer):
        if serializer.instance.status not in self._EDITABLE_STATUSES:
            raise ValidationError({"purchase_order": "Only draft or ordered purchase orders can be edited."})
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status not in self._EDITABLE_STATUSES:
            raise ValidationError({"purchase_order": "Only draft or ordered purchase orders can be deleted."})
        instance.delete()


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user", "branch__company")
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        from .sales_control import _parse_iso_date

        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        action_value = self.request.query_params.get("action")
        entity = self.request.query_params.get("entity")
        user_id = _positive_int_query_param(self.request.query_params, "user")
        sales_only = self.request.query_params.get("sales_only")
        date_from = _parse_iso_date(self.request.query_params.get("date_from"), "date_from")
        date_to = _parse_iso_date(self.request.query_params.get("date_to"), "date_to")
        search = (self.request.query_params.get("search") or "").strip()

        if action_value:
            queryset = queryset.filter(action__icontains=action_value)
        if entity:
            queryset = queryset.filter(entity__iexact=entity)
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        if sales_only in {"1", "true", "yes"}:
            queryset = queryset.filter(
                Q(action__startswith="sale")
                | Q(action__startswith="sale_return")
                | Q(action__startswith="cash.")
                | Q(action__startswith="receipt.")
            )
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        if search:
            queryset = queryset.filter(
                Q(notes__icontains=search)
                | Q(entity__icontains=search)
                | Q(entity_id__icontains=search)
                | Q(user__username__icontains=search)
            )
        return queryset
