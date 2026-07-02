import datetime

from django.db.models import Count, Q, Sum as DbSum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import CashTransaction, Payment, Sale, SaleReturn, Shift
from .serializers import (
    ApproveSaleReturnSerializer,
    CashTransactionSerializer,
    CompleteSaleReturnSerializer,
    CreateCashTransactionSerializer,
    CreateSaleReturnSerializer,
    PaymentSerializer,
    RejectSaleReturnSerializer,
    SaleReturnSerializer,
)
from .services import (
    approve_sale_return,
    complete_sale_return,
    create_sale_return,
    record_cash_transaction,
    reject_sale_return,
)
from .views import (
    _filter_branch_scoped_queryset,
    _positive_int_query_param,
    _resolve_read_branch,
)


def _parse_iso_date(value, name):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: "Expected YYYY-MM-DD."}) from exc


def apply_sales_filters(queryset, request):
    search = (request.query_params.get("search") or "").strip()
    status_value = request.query_params.get("status")
    customer = _positive_int_query_param(request.query_params, "customer")
    cashier = _positive_int_query_param(request.query_params, "cashier")
    shift_id = _positive_int_query_param(request.query_params, "shift")
    register = _positive_int_query_param(request.query_params, "register")
    payment_method = request.query_params.get("payment_method")
    mode = request.query_params.get("mode")
    date_from = _parse_iso_date(request.query_params.get("date_from"), "date_from")
    date_to = _parse_iso_date(request.query_params.get("date_to"), "date_to")

    if status_value:
        queryset = queryset.filter(status=status_value)
    if customer is not None:
        queryset = queryset.filter(customer_id=customer)
    if cashier is not None:
        queryset = queryset.filter(cashier_id=cashier)
    if shift_id is not None:
        queryset = queryset.filter(shift_id=shift_id)
    if register is not None:
        queryset = queryset.filter(register_id=register)
    if mode:
        queryset = queryset.filter(mode=mode)
    if payment_method:
        queryset = queryset.filter(payments__method=payment_method).distinct()
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    if search:
        queryset = queryset.filter(
            Q(receipt_no__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(cashier__username__icontains=search)
            | Q(items__product__name__icontains=search)
        ).distinct()
    return queryset


def sales_control_dashboard(queryset, shift_queryset):
    paid = queryset.filter(status=Sale.PAID)
    voided = queryset.filter(status=Sale.VOIDED)
    paid_agg = paid.aggregate(total=DbSum("total"), count=Count("id"))
    void_agg = voided.aggregate(total=DbSum("total"), count=Count("id"))
    open_shifts = shift_queryset.filter(status=Shift.OPEN).count()
    branch_ids = queryset.values_list("branch_id", flat=True).distinct()
    pending_returns = SaleReturn.objects.filter(branch_id__in=branch_ids, status=SaleReturn.PENDING).count()
    return {
        "paid_sales_count": paid_agg["count"] or 0,
        "paid_sales_total": paid_agg["total"] or 0,
        "voided_sales_count": void_agg["count"] or 0,
        "voided_sales_total": void_agg["total"] or 0,
        "open_shifts": open_shifts,
        "pending_returns": pending_returns,
    }


def build_sales_report(queryset, report_type):
    if report_type == "daily_summary":
        rows = (
            queryset.filter(status=Sale.PAID)
            .values("created_at__date")
            .annotate(sales_count=Count("id"), total=DbSum("total"), tax=DbSum("tax_total"))
            .order_by("-created_at__date")
        )
        return {"report": report_type, "rows": list(rows)}

    if report_type == "cashier":
        rows = (
            queryset.filter(status=Sale.PAID)
            .values("cashier_id", "cashier__username")
            .annotate(sales_count=Count("id"), total=DbSum("total"))
            .order_by("-total")
        )
        return {"report": report_type, "rows": list(rows)}

    if report_type == "branch":
        rows = (
            queryset.filter(status=Sale.PAID)
            .values("branch_id", "branch__name")
            .annotate(sales_count=Count("id"), total=DbSum("total"))
            .order_by("-total")
        )
        return {"report": report_type, "rows": list(rows)}

    if report_type == "payments":
        payments = Payment.objects.filter(sale__in=queryset.filter(status=Sale.PAID))
        rows = (
            payments.values("method")
            .annotate(count=Count("id"), total=DbSum("amount"))
            .order_by("-total")
        )
        return {"report": report_type, "rows": list(rows)}

    if report_type == "voids_refunds":
        void_rows = (
            queryset.filter(status=Sale.VOIDED)
            .values("created_at__date")
            .annotate(void_count=Count("id"), void_total=DbSum("total"))
            .order_by("-created_at__date")
        )
        return_rows = (
            SaleReturn.objects.filter(sale__in=queryset, status=SaleReturn.COMPLETED)
            .values("created_at__date")
            .annotate(return_count=Count("id"), refund_total=DbSum("total_refund"))
            .order_by("-created_at__date")
        )
        return {
            "report": report_type,
            "voids": list(void_rows),
            "returns": list(return_rows),
        }

    raise ValidationError({"report": "Expected one of: daily_summary, cashier, branch, payments, voids_refunds."})


def _payment_totals_for_shift(shift):
    payments = Payment.objects.filter(sale__shift=shift, sale__status=Sale.PAID)
    totals = {}
    for method, _label in Payment.METHOD_CHOICES:
        totals[method] = payments.filter(method=method).aggregate(total=DbSum("amount"))["total"] or 0
    return totals


def shift_cash_summary(shift):
    from decimal import Decimal

    from .services import quantize_money

    paid_sales = shift.sales.filter(status=Sale.PAID)
    sales_count = paid_sales.count()
    sales_total = paid_sales.aggregate(total=DbSum("total"))["total"] or Decimal("0.00")
    payment_totals = _payment_totals_for_shift(shift)

    # Cash payment amounts include what the customer tendered (may exceed sale total).
    # Change is always returned in cash, so deduct total change_due to get net cash revenue.
    total_change = paid_sales.aggregate(total=DbSum("change_due"))["total"] or Decimal("0.00")
    raw_cash = Decimal(str(payment_totals.get(Payment.CASH, 0)))
    payment_totals[Payment.CASH] = max(Decimal("0.00"), raw_cash - total_change)

    cash_out_types = [CashTransaction.CASH_OUT, CashTransaction.PAYOUT, CashTransaction.DROP]
    tx_cash_in = shift.cash_transactions.filter(transaction_type=CashTransaction.CASH_IN).aggregate(total=DbSum("amount"))["total"] or 0
    tx_cash_out = shift.cash_transactions.filter(transaction_type__in=cash_out_types).aggregate(total=DbSum("amount"))["total"] or 0

    expected = shift.expected_cash
    counted = shift.counted_cash
    if shift.status == Shift.CLOSED:
        variance = shift.cash_variance
    elif counted is not None:
        variance = quantize_money(counted - expected)
    else:
        variance = Decimal("0.00")

    variance_num = float(variance)
    if variance_num > 0:
        variance_status = "over"
    elif variance_num < 0:
        variance_status = "short"
    else:
        variance_status = "balanced"

    return {
        "shift_id": shift.id,
        "cashier_id": shift.cashier_id,
        "cashier_name": shift.cashier.get_username() if shift.cashier_id else "",
        "register_id": shift.register_id,
        "register_code": shift.register.code if shift.register_id else "",
        "branch_id": shift.branch_id,
        "branch_name": shift.branch.name if shift.branch_id else "",
        "opened_at": shift.opened_at,
        "closed_at": shift.closed_at,
        "opening_cash": shift.opening_cash,
        "expected_cash": expected,
        "counted_cash": counted,
        "cash_variance": variance,
        "variance_status": variance_status,
        "cash_sales_total": payment_totals.get(Payment.CASH, 0),
        "mpesa_sales_total": payment_totals.get(Payment.MPESA, 0),
        "card_sales_total": payment_totals.get(Payment.CARD, 0),
        "credit_sales_total": payment_totals.get(Payment.CREDIT, 0),
        "manual_cash_in": tx_cash_in,
        "manual_cash_out": tx_cash_out,
        "sales_count": sales_count,
        "sales_total": sales_total,
        "status": shift.status,
    }


class SaleReturnViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        SaleReturn.objects
        .select_related("sale", "branch__company", "shift", "processed_by", "approved_by")
        .prefetch_related("items__product")
    )
    serializer_class = SaleReturnSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        status_value = self.request.query_params.get("status")
        sale_id = _positive_int_query_param(self.request.query_params, "sale")
        if status_value:
            queryset = queryset.filter(status=status_value)
        if sale_id is not None:
            queryset = queryset.filter(sale_id=sale_id)
        return queryset

    @action(detail=False, methods=["post"])
    def create_return(self, request):
        serializer = CreateSaleReturnSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        sale_return = create_sale_return(processed_by=request.user, **serializer.validated_data)
        return Response(SaleReturnSerializer(sale_return).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        sale_return = approve_sale_return(sale_return=self.get_object(), user=request.user)
        return Response(SaleReturnSerializer(sale_return).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        serializer = RejectSaleReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale_return = reject_sale_return(
            sale_return=self.get_object(),
            user=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(SaleReturnSerializer(sale_return).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        sale_return = complete_sale_return(sale_return=self.get_object(), user=request.user)
        return Response(SaleReturnSerializer(sale_return).data)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Payment.objects.select_related("sale__branch__company", "sale__cashier", "sale__customer")
    serializer_class = PaymentSerializer

    def get_queryset(self):
        branch = _resolve_read_branch(self.request)
        queryset = super().get_queryset()
        if not branch:
            return queryset.none()
        queryset = queryset.filter(sale__branch=branch)
        method = self.request.query_params.get("method")
        sale_status = self.request.query_params.get("sale_status")
        search = (self.request.query_params.get("search") or "").strip()
        date_from = _parse_iso_date(self.request.query_params.get("date_from"), "date_from")
        date_to = _parse_iso_date(self.request.query_params.get("date_to"), "date_to")
        if method:
            queryset = queryset.filter(method=method)
        if sale_status:
            queryset = queryset.filter(sale__status=sale_status)
        if date_from:
            queryset = queryset.filter(sale__created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(sale__created_at__date__lte=date_to)
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(sale__receipt_no__icontains=search)
            )
        return queryset.order_by("-created_at")


class CashTransactionViewSet(viewsets.ModelViewSet):
    queryset = CashTransaction.objects.select_related("shift", "branch__company", "user")
    serializer_class = CashTransactionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        shift_id = _positive_int_query_param(self.request.query_params, "shift")
        tx_type = self.request.query_params.get("transaction_type")
        if shift_id is not None:
            queryset = queryset.filter(shift_id=shift_id)
        if tx_type:
            queryset = queryset.filter(transaction_type=tx_type)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = CreateCashTransactionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        cash_tx = record_cash_transaction(**serializer.validated_data)
        return Response(CashTransactionSerializer(cash_tx).data, status=status.HTTP_201_CREATED)
