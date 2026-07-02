"""Shift, Sale and HeldOrder viewsets."""
import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, F, OuterRef, Q, Subquery, Sum as DbSum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import (
    DiscountRule,
    HeldOrder,
    HeldOrderItem,
    InventoryStock,
    MpesaDirectPaymentLog,
    MpesaStkLog,
    Payment,
    Register,
    Sale,
    SaleItem,
    Shift,
)
from .serializers import (
    CheckoutSerializer,
    CloseShiftSerializer,
    HeldOrderSerializer,
    HoldOrderSerializer,
    MpesaDirectLookupSerializer,
    MpesaStkPushSerializer,
    MpesaStkQuerySerializer,
    OpenShiftSerializer,
    ReceiptCopySerializer,
    SaleSerializer,
    ShiftSerializer,
    UpdateHoldOrderSerializer,
    VoidSaleSerializer,
)
from .services import (
    checkout_sale,
    close_shift,
    reprint_receipt,
    void_sale,
)
from .views_helpers import (
    _filter_branch_scoped_queryset,
    _is_cashier_only,
    _positive_int_query_param,
    _resolve_read_branch,
    _resolve_write_branch,
)

logger = logging.getLogger(__name__)


def _apply_discount_rules(branch, mode, items):
    """Compute and inject discount_amount for each validated checkout item."""
    active_rules = [
        r for r in DiscountRule.objects.filter(branch=branch, is_active=True)
        .select_related('product', 'category')
        if r.is_active_now()
    ]
    if not active_rules:
        return
    is_wholesale = (mode == Sale.WHOLESALE)
    for item_data in items:
        product = item_data['product']
        qty = item_data['quantity']
        unit_price = Decimal(str(product.wholesale_price if is_wholesale else product.retail_price))
        gross = unit_price * qty
        # Priority: product-specific > category > all-products
        matching_rule = None
        for rule in active_rules:
            if rule.target == DiscountRule.BY_PRODUCT and rule.product_id == product.pk:
                matching_rule = rule
                break
        if not matching_rule:
            for rule in active_rules:
                if rule.target == DiscountRule.BY_CATEGORY and product.category_id and rule.category_id == product.category_id:
                    matching_rule = rule
                    break
        if not matching_rule:
            for rule in active_rules:
                if rule.target == DiscountRule.ALL_PRODUCTS:
                    matching_rule = rule
                    break
        if matching_rule:
            if matching_rule.discount_type == DiscountRule.PERCENT:
                disc = (gross * matching_rule.value / Decimal('100')).quantize(Decimal('0.01'))
            else:
                disc = min(matching_rule.value, gross).quantize(Decimal('0.01'))
            item_data['discount_amount'] = disc


def _user_can_void(user):
    """Return True if user has permission to void sales."""
    try:
        profile = user.pos_profile
    except Exception:
        return False
    if profile.access_level in ("super_admin", "company_admin", "branch_admin"):
        return True
    if profile.role in ("admin", "manager"):
        return True
    if profile.use_custom_permissions and "sale.void" in (profile.custom_permissions or []):
        return True
    return False


class ShiftViewSet(viewsets.ModelViewSet):
    queryset = Shift.objects.select_related("branch__company", "register", "cashier")
    serializer_class = ShiftSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        branch_param = _positive_int_query_param(self.request.query_params, "branch")
        register = _positive_int_query_param(self.request.query_params, "register")
        cashier = _positive_int_query_param(self.request.query_params, "cashier")
        status_value = self.request.query_params.get("status")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if branch_param is not None:
            queryset = queryset.filter(branch_id=branch_param)
        if register is not None:
            queryset = queryset.filter(register_id=register)
        if cashier is not None:
            queryset = queryset.filter(cashier_id=cashier)
        if date_from:
            try:
                queryset = queryset.filter(opened_at__date__gte=datetime.date.fromisoformat(date_from))
            except ValueError as exc:
                raise ValidationError({"date_from": "Expected YYYY-MM-DD."}) from exc
        if date_to:
            try:
                queryset = queryset.filter(opened_at__date__lte=datetime.date.fromisoformat(date_to))
            except ValueError as exc:
                raise ValidationError({"date_to": "Expected YYYY-MM-DD."}) from exc
        if status_value:
            if status_value not in dict(Shift.STATUS_CHOICES):
                raise ValidationError({"status": "Expected one of: open, closed."})
            queryset = queryset.filter(status=status_value)
        # Cashiers can only see their own shifts, not colleagues'
        if _is_cashier_only(self.request.user):
            queryset = queryset.filter(cashier=self.request.user)
        return queryset

    @action(detail=False, methods=["get"], url_path="cash-management")
    def cash_management(self, request):
        return self.cashier_summary(request)

    @action(detail=False, methods=["get"], url_path="cashier-summary")
    def cashier_summary(self, request):
        from .sales_control import shift_cash_summary
        queryset = self.get_queryset().select_related("cashier", "register", "branch").order_by("-opened_at")
        search = (request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(cashier__username__icontains=search)
                | Q(cashier__first_name__icontains=search)
                | Q(cashier__last_name__icontains=search)
                | Q(register__code__icontains=search)
            )
        page = self.paginate_queryset(queryset)
        rows = [shift_cash_summary(shift) for shift in (page if page is not None else queryset)]
        if page is not None:
            return self.get_paginated_response(rows)
        return Response(rows)

    @action(detail=False, methods=["get"])
    def performance(self, request):
        shifts = self.get_queryset().select_related("cashier").order_by("-opened_at")
        rows = []
        for shift in shifts:
            sales = shift.sales.filter(status=Sale.PAID)
            agg = sales.aggregate(count=Count("id"), total=DbSum("total"))
            rows.append({**ShiftSerializer(shift).data, "sales_count": agg["count"] or 0, "sales_total": agg["total"] or 0})
        return Response(rows)

    @action(detail=True, methods=["get"], url_path="cash-summary")
    def cash_summary(self, request, pk=None):
        from .sales_control import shift_cash_summary
        return Response(shift_cash_summary(self.get_object()))

    @action(detail=False, methods=["post"])
    def open(self, request):
        serializer = OpenShiftSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        register = serializer.validated_data["register"]
        existing_shift = Shift.objects.filter(register=register, status=Shift.OPEN).first()
        if existing_shift:
            return Response(ShiftSerializer(existing_shift).data, status=status.HTTP_200_OK)
        try:
            with transaction.atomic():
                shift = Shift.objects.create(
                    **serializer.validated_data,
                    expected_cash=serializer.validated_data["opening_cash"],
                )
        except IntegrityError:
            shift = Shift.objects.filter(register=register, status=Shift.OPEN).first()
            if not shift:
                raise
            return Response(ShiftSerializer(shift).data, status=status.HTTP_200_OK)
        return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        serializer = CloseShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shift = close_shift(shift=self.get_object(), counted_cash=serializer.validated_data["counted_cash"])
        return Response(ShiftSerializer(shift).data)


class SaleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Sale.objects
        .select_related("branch__company", "register", "shift", "cashier", "customer", "voided_by")
        .prefetch_related("items__product", "payments", "receipt_copies")
    )
    serializer_class = SaleSerializer

    def get_queryset(self):
        from .sales_control import apply_sales_filters
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        queryset = apply_sales_filters(queryset, self.request)
        # Cashiers can only see their own transactions, not colleagues'
        if _is_cashier_only(self.request.user):
            queryset = queryset.filter(cashier=self.request.user)
        return queryset

    @action(detail=False, methods=["get"])
    def control(self, request):
        from .sales_control import sales_control_dashboard
        sales_qs = self.get_queryset()
        branch = _resolve_read_branch(request)
        shift_qs = Shift.objects.filter(branch=branch) if branch else Shift.objects.none()
        return Response(sales_control_dashboard(sales_qs, shift_qs))

    @action(detail=False, methods=["get"])
    def transactions(self, request):
        queryset = self.filter_queryset(self.get_queryset().filter(status=Sale.PAID))
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"])
    def voids(self, request):
        queryset = self.filter_queryset(self.get_queryset().filter(status=Sale.VOIDED))
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"])
    def discounts(self, request):
        queryset = self.filter_queryset(
            self.get_queryset().filter(discount_total__gt=0)
        )
        search = (request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(receipt_no__icontains=search)
                | Q(cashier__username__icontains=search)
                | Q(customer__name__icontains=search)
            )
        queryset = queryset.order_by("-created_at")
        page = self.paginate_queryset(queryset)
        sales = page if page is not None else queryset[:100]
        rows = []
        for sale in sales:
            cashier = sale.cashier
            discounted_items = [
                {"product_name": i.product.name, "discount_amount": str(i.discount_amount)}
                for i in sale.items.all()
                if i.discount_amount and i.discount_amount > 0
            ]
            rows.append({
                "receipt_no": sale.receipt_no,
                "sale_id": sale.id,
                "cashier_name": (cashier.get_full_name() or cashier.get_username()) if cashier else "",
                "customer_name": sale.customer.name if sale.customer else "Walk-in",
                "subtotal": str(sale.subtotal or sale.total),
                "discount_total": str(sale.discount_total or 0),
                "total": str(sale.total),
                "created_at": sale.created_at,
                "status": sale.status,
                "items_discounted": discounted_items,
            })
        if page is not None:
            return self.get_paginated_response(rows)
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="customer-sales")
    def customer_sales(self, request):
        from decimal import Decimal as D
        from django.db.models import Max, OuterRef, Subquery, DecimalField as DjangoDecimalField
        branch = _resolve_read_branch(request)
        if not branch:
            return Response([])
        sales = self.get_queryset().filter(status=Sale.PAID, customer__isnull=False)
        # Credit total per customer via correlated subquery — eliminates N+1 loop
        credit_sq = (
            Payment.objects
            .filter(
                sale__customer_id=OuterRef("customer_id"),
                sale__branch=branch,
                sale__status=Sale.PAID,
                method=Payment.CREDIT,
            )
            .values("sale__customer_id")
            .annotate(t=DbSum("amount"))
            .values("t")[:1]
        )
        grouped = (
            sales.values("customer_id", "customer__name")
            .annotate(
                total_spent=DbSum("total"),
                receipt_count=Count("id"),
                last_purchase=Max("created_at"),
                credit_sales=Subquery(credit_sq, output_field=DjangoDecimalField()),
            )
            .order_by("-total_spent")
        )
        page_size = int(request.query_params.get("page_size", 50))
        page_num = int(request.query_params.get("page", 1))
        total = grouped.count()
        offset = (page_num - 1) * page_size
        rows = [
            {
                "customer_id": row["customer_id"],
                "customer_name": row["customer__name"],
                "total_spent": row["total_spent"] or 0,
                "receipt_count": row["receipt_count"] or 0,
                "last_purchase": row["last_purchase"],
                "credit_sales": row["credit_sales"] or 0,
            }
            for row in grouped[offset: offset + page_size]
        ]
        return Response({"count": total, "results": rows})

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        """
        Single-query dashboard summary — replaces N×3 product/sale/shift API calls from the frontend.
        Returns branch_stats, sales_trend, payment_mix, low_stock_alerts, recent_sales.
        """
        from django.db.models.functions import TruncDate

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        branch_ids_param = request.query_params.get("branch_ids", "")

        # Resolve requested branch IDs (security: scoped by _filter_branch_scoped_queryset)
        if branch_ids_param:
            requested_ids = [int(x) for x in branch_ids_param.split(",") if x.strip().isdigit()]
        else:
            b = _resolve_read_branch(request)
            requested_ids = [b.id] if b else []

        if not requested_ids:
            empty = {"branch_stats": [], "sales_trend": [], "payment_mix": [], "low_stock_alerts": [], "recent_sales": []}
            return Response(empty)

        # Base paid-sales queryset scoped to accessible branches
        base_qs = _filter_branch_scoped_queryset(
            Sale.objects.filter(status=Sale.PAID, branch_id__in=requested_ids), request
        )
        if date_from:
            base_qs = base_qs.filter(created_at__date__gte=date_from)
        if date_to:
            base_qs = base_qs.filter(created_at__date__lte=date_to)

        # Revenue + sale count per branch (1 query)
        rev_map = {
            row["branch_id"]: {"revenue": float(row["rev"] or 0), "sale_count": row["cnt"]}
            for row in base_qs.values("branch_id").annotate(rev=DbSum("total"), cnt=Count("id"))
        }

        # Gross profit per branch: sum((unit_price - cost_price) * quantity) (1 query)
        gp_map = {
            row["sale__branch_id"]: float(row["gp"] or 0)
            for row in SaleItem.objects.filter(sale__in=base_qs).values("sale__branch_id").annotate(
                gp=DbSum((F("unit_price") - F("product__cost_price")) * F("quantity"), output_field=DecimalField())
            )
        }

        # Shift cash variance per branch (1 query)
        shift_qs = Shift.objects.filter(branch_id__in=requested_ids)
        if date_from:
            shift_qs = shift_qs.filter(opened_at__date__gte=date_from)
        if date_to:
            shift_qs = shift_qs.filter(opened_at__date__lte=date_to)
        var_map = {
            row["branch_id"]: float((row["counted"] or 0) - (row["expected"] or 0))
            for row in shift_qs.values("branch_id").annotate(
                expected=DbSum("expected_cash"), counted=DbSum("counted_cash")
            )
        }

        # Daily sales trend, all branches combined (1 query)
        sales_trend = [
            {"date": str(row["d"]), "total": float(row["total"] or 0), "count": row["count"]}
            for row in base_qs.annotate(d=TruncDate("created_at"))
            .values("d").annotate(total=DbSum("total"), count=Count("id")).order_by("d")
        ]

        # Payment mix (1 query)
        payment_mix = [
            {"method": row["method"], "total": float(row["total"] or 0)}
            for row in Payment.objects.filter(sale__in=base_qs)
            .values("method").annotate(total=DbSum("amount")).order_by("-total")
        ]

        # Low-stock count + top alerts (1 query)
        low_qs = (
            InventoryStock.objects
            .filter(branch_id__in=requested_ids, product__is_active=True)
            .filter(quantity__lte=F("product__reorder_point"))
            .select_related("product")
        )
        low_count_map = {}
        low_alerts = []
        for row in low_qs:
            low_count_map[row.branch_id] = low_count_map.get(row.branch_id, 0) + 1
            if len(low_alerts) < 8:
                low_alerts.append({
                    "product_id": row.product_id,
                    "name": row.product.name,
                    "stock": row.quantity,
                    "reorder_point": row.product.reorder_point,
                    "branch_id": row.branch_id,
                })

        # Stock value per branch (1 query)
        sv_map = {
            row["branch_id"]: float(row["sv"] or 0)
            for row in InventoryStock.objects.filter(branch_id__in=requested_ids, product__is_active=True)
            .values("branch_id")
            .annotate(sv=DbSum(F("quantity") * F("product__cost_price"), output_field=DecimalField()))
        }

        # Recent sales for the dashboard table (1 query)
        recent = (
            base_qs.select_related("cashier").prefetch_related("payments")
            .order_by("-created_at")[:10]
        )
        recent_sales = [
            {
                "id": s.id,
                "receipt_no": s.receipt_no,
                "cashier_name": (s.cashier.get_full_name() or s.cashier.username) if s.cashier else "—",
                "total": str(s.total),
                "payments": [{"method": p.method, "amount": str(p.amount)} for p in s.payments.all()],
                "created_at": s.created_at.isoformat(),
            }
            for s in recent
        ]

        branch_stats = [
            {
                "branch_id": bid,
                "revenue": rev_map.get(bid, {}).get("revenue", 0),
                "sale_count": rev_map.get(bid, {}).get("sale_count", 0),
                "gross_profit": gp_map.get(bid, 0),
                "cash_variance": var_map.get(bid, 0),
                "low_stock_count": low_count_map.get(bid, 0),
                "stock_value": sv_map.get(bid, 0),
            }
            for bid in requested_ids
        ]

        return Response({
            "branch_stats": branch_stats,
            "sales_trend": sales_trend,
            "payment_mix": payment_mix,
            "low_stock_alerts": low_alerts,
            "recent_sales": recent_sales,
        })

    @action(detail=False, methods=["get"])
    def reports(self, request):
        from .sales_control import build_sales_report
        report_type = request.query_params.get("type", "daily_summary")
        return Response(build_sales_report(self.get_queryset(), report_type))

    @action(detail=False, methods=["post"])
    def checkout(self, request):
        serializer = CheckoutSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as exc:
            try:
                if getattr(settings, "DEBUG", False):
                    logger.error("Checkout validation failed: %s", getattr(serializer, "errors", exc))
                    logger.error("Checkout payload: %s", request.data)
            except Exception:
                pass
            raise

        validated = dict(serializer.validated_data)
        initiate_stk = validated.pop("initiate_stk", False)
        mpesa_checkout_request_id = (validated.pop("mpesa_checkout_request_id", "") or "").strip()
        mpesa_direct_transaction_id = (validated.pop("mpesa_direct_transaction_id", "") or "").strip().upper()
        mpesa_manual_approval = bool(validated.pop("mpesa_manual_approval", False))
        # Offline sync fields: device_id for namespace, receipt_no from offline device
        device_id = (validated.pop("device_id", "") or "").strip()
        receipt_no = (validated.pop("receipt_no", "") or "").strip()
        if device_id:
            validated["device_id"] = device_id
        if receipt_no:
            validated["receipt_no"] = receipt_no
        mpesa_payments = [p for p in validated.get("payments", []) if p.get("method") == Payment.MPESA]

        paid_mpesa_log = None
        direct_mpesa_log = None
        if mpesa_payments:
            from .utils.mpesa import branch_has_mpesa_credentials
            branch_obj = validated.get("branch")
            branch_has_mpesa = branch_has_mpesa_credentials(branch_obj)

            if initiate_stk:
                raise ValidationError({"mpesa_stk": "Send STK first, wait for successful callback, then complete the sale."})

            mpesa_total = sum((p.get("amount") for p in mpesa_payments), Decimal("0.00"))
            if mpesa_direct_transaction_id:
                direct_mpesa_log = MpesaDirectPaymentLog.objects.filter(
                    branch=branch_obj, transaction_id=mpesa_direct_transaction_id,
                    result_code=0, success=True, sale__isnull=True,
                ).order_by("-created_at").first()
                if not direct_mpesa_log:
                    raise ValidationError({"mpesa_direct": "Direct M-Pesa payment is not verified yet."})
                if direct_mpesa_log.amount is not None and direct_mpesa_log.amount != mpesa_total:
                    raise ValidationError({"mpesa_direct": "Verified M-Pesa amount does not match this sale."})
            elif branch_has_mpesa:
                if not mpesa_checkout_request_id:
                    if mpesa_manual_approval:
                        if not getattr(branch_obj, "mpesa_manual_approval_enabled", False):
                            raise ValidationError({"mpesa_manual_approval": "Manual M-Pesa approval is not enabled for this branch."})
                        paid_mpesa_log = None
                    else:
                        raise ValidationError({"mpesa_stk": "M-Pesa sale requires a successful STK callback before checkout."})
                else:
                    paid_mpesa_log = MpesaStkLog.objects.filter(
                        branch=branch_obj, checkout_request_id=mpesa_checkout_request_id,
                        result_code=0, success=True, sale__isnull=True,
                    ).order_by("-created_at").first()
                    if not paid_mpesa_log:
                        raise ValidationError({"mpesa_stk": "M-Pesa payment is not confirmed yet. Wait for callback success before completing sale."})
                    if paid_mpesa_log.amount != mpesa_total:
                        raise ValidationError({"mpesa_stk": "Confirmed M-Pesa amount does not match this sale."})
            else:
                paid_mpesa_log = None

        mpesa_stk_results = []
        if initiate_stk:
            from .utils.mpesa import initiate_stk_push
            import re
            for p in validated.get("payments", []):
                if p.get("method") == Payment.MPESA:
                    ref = (p.get("reference") or "").split("|")[0].strip()
                    phone = re.sub(r"\D", "", ref)
                    if phone.startswith("0"):
                        phone = "254" + phone.lstrip("0")
                    result = initiate_stk_push(
                        phone=phone, amount=p.get("amount"),
                        reference=p.get("reference", ""), branch=validated.get("branch"),
                    )
                    mpesa_stk_results.append({"payment_reference": p.get("reference", ""), "result": result})
            failed = [r for r in mpesa_stk_results if not r["result"].get("success")]
            if failed:
                messages = [f"{r['payment_reference']}: {r['result'].get('message', 'STK failed')}" for r in failed]
                raise ValidationError({"mpesa_stk": "; ".join(messages)})

        _apply_discount_rules(
            branch=validated.get('branch'),
            mode=validated.get('mode', Sale.RETAIL),
            items=validated.get('items', []),
        )
        sale = checkout_sale(**validated)
        if paid_mpesa_log:
            mpesa_payment = sale.payments.filter(method=Payment.MPESA).first()
            paid_mpesa_log.sale = sale
            paid_mpesa_log.payment = mpesa_payment
            paid_mpesa_log.save(update_fields=["sale", "payment", "updated_at"])
        if direct_mpesa_log:
            mpesa_payment = sale.payments.filter(method=Payment.MPESA).first()
            direct_mpesa_log.sale = sale
            direct_mpesa_log.payment = mpesa_payment
            direct_mpesa_log.save(update_fields=["sale", "payment", "updated_at"])

        response_data = SaleSerializer(sale).data
        if mpesa_stk_results:
            response_data["mpesa_stk_results"] = mpesa_stk_results
        return Response(response_data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="mpesa/stk-push")
    def mpesa_stk_push(self, request):
        serializer = MpesaStkPushSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        from .utils.mpesa import initiate_stk_push
        result = initiate_stk_push(
            phone=serializer.validated_data["phone"],
            amount=serializer.validated_data["amount"],
            reference=serializer.validated_data.get("reference", ""),
            description=serializer.validated_data.get("description", ""),
            branch=serializer.validated_data.get("branch"),
        )
        if not result.get("success"):
            raise ValidationError({"mpesa": result.get("message")})
        return Response(result)

    @action(detail=False, methods=["post"], url_path="mpesa/stk-query")
    def mpesa_stk_query(self, request):
        serializer = MpesaStkQuerySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        from .utils.mpesa import query_stk_status
        result = query_stk_status(serializer.validated_data["checkout_request_id"], branch=serializer.validated_data.get("branch"))
        if not result.get("success"):
            raise ValidationError({"mpesa": result.get("message")})
        return Response(result)

    @action(detail=False, methods=["post"], url_path="mpesa/direct-lookup")
    def mpesa_direct_lookup(self, request):
        serializer = MpesaDirectLookupSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        from .utils.mpesa import initiate_direct_payment_lookup
        result = initiate_direct_payment_lookup(
            transaction_id=serializer.validated_data["transaction_id"],
            amount=serializer.validated_data.get("amount"),
            branch=serializer.validated_data.get("branch"),
        )
        if not result.get("success"):
            raise ValidationError({"mpesa": result.get("message")})
        return Response(result)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        if not _user_can_void(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have permission to void sales.")
        serializer = VoidSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = void_sale(
            sale=self.get_object(),
            user=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(SaleSerializer(sale).data)

    @action(detail=True, methods=["post"], url_path="reprint")
    def reprint(self, request, pk=None):
        copy = reprint_receipt(sale=self.get_object(), user=request.user)
        return Response(ReceiptCopySerializer(copy).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        sales = self.get_queryset().filter(status=Sale.PAID)
        total = sum((sale.total for sale in sales), 0)
        paid_count = sales.count()
        voided_count = self.get_queryset().filter(status=Sale.VOIDED).count()
        return Response({"paid_sales": paid_count, "voided_sales": voided_count, "total": total})

    @action(detail=False, methods=["get"], url_path="cashier-performance")
    def cashier_performance(self, request):
        """Per-cashier aggregated sales: total, count, avg, items, voids."""
        from django.db.models import Avg, Count as DCount
        branch = _resolve_read_branch(request)
        if not branch:
            return Response([])
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        def _scoped(status_val):
            qs = Sale.objects.filter(branch=branch, status=status_val)
            if date_from:
                qs = qs.filter(created_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(created_at__date__lte=date_to)
            return qs

        paid = (
            _scoped(Sale.PAID)
            .values("cashier_id", "cashier__username", "cashier__first_name", "cashier__last_name")
            .annotate(
                total_sales=DbSum("total"),
                total_discounts=DbSum("discount_total"),
                sale_count=Count("id"),
                avg_sale=Avg("total"),
            )
            .order_by("-total_sales")
        )
        item_sums = {
            row["sale__cashier_id"]: row["qty"]
            for row in SaleItem.objects.filter(sale__branch=branch, sale__status=Sale.PAID)
            .values("sale__cashier_id")
            .annotate(qty=DbSum("quantity"))
        } if not date_from and not date_to else {
            row["sale__cashier_id"]: row["qty"]
            for row in SaleItem.objects.filter(
                sale__branch=branch, sale__status=Sale.PAID,
                **({} if not date_from else {"sale__created_at__date__gte": date_from}),
                **({} if not date_to else {"sale__created_at__date__lte": date_to}),
            )
            .values("sale__cashier_id")
            .annotate(qty=DbSum("quantity"))
        }
        void_counts = {
            row["cashier_id"]: row["cnt"]
            for row in _scoped(Sale.VOIDED).values("cashier_id").annotate(cnt=Count("id"))
        }
        rows = []
        for row in paid:
            cid = row["cashier_id"]
            full = " ".join(filter(None, [row.get("cashier__first_name", ""), row.get("cashier__last_name", "")])).strip()
            rows.append({
                "cashier_id": cid,
                "cashier_name": full or row.get("cashier__username", ""),
                "username": row.get("cashier__username", ""),
                "total_sales": float(row["total_sales"] or 0),
                "total_discounts": float(row["total_discounts"] or 0),
                "sale_count": row["sale_count"] or 0,
                "avg_sale": float(row["avg_sale"] or 0),
                "items_sold": item_sums.get(cid, 0),
                "void_count": void_counts.get(cid, 0),
            })
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="product-sales")
    def product_sales(self, request):
        """Top products by revenue for the filtered period."""
        branch = _resolve_read_branch(request)
        if not branch:
            return Response([])
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        qs = SaleItem.objects.filter(sale__branch=branch, sale__status=Sale.PAID)
        if date_from:
            qs = qs.filter(sale__created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(sale__created_at__date__lte=date_to)
        rows = (
            qs.values("product_id", "product__name", "product__sku", "product__category__name")
            .annotate(
                qty_sold=DbSum("quantity"),
                revenue=DbSum(F("quantity") * F("unit_price"), output_field=DecimalField()),
                total_discounts=DbSum("discount_amount"),
                tx_count=Count("sale", distinct=True),
            )
            .order_by("-revenue")[:100]
        )
        return Response([
            {
                "product_id": r["product_id"],
                "product_name": r["product__name"],
                "sku": r["product__sku"],
                "category": r["product__category__name"],
                "qty_sold": r["qty_sold"] or 0,
                "revenue": float(r["revenue"] or 0),
                "total_discounts": float(r["total_discounts"] or 0),
                "tx_count": r["tx_count"] or 0,
            }
            for r in rows
        ])

    @action(detail=False, methods=["get"], url_path="hourly-sales")
    def hourly_sales(self, request):
        """Sales aggregated by hour-of-day for heatmap / busy-period analysis."""
        from django.db.models.functions import ExtractHour
        branch = _resolve_read_branch(request)
        if not branch:
            return Response([])
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        qs = Sale.objects.filter(branch=branch, status=Sale.PAID)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        rows = (
            qs.annotate(hour=ExtractHour("created_at"))
            .values("hour")
            .annotate(total=DbSum("total"), total_discounts=DbSum("discount_total"), count=Count("id"))
            .order_by("hour")
        )
        return Response([
            {"hour": f"{r['hour']:02d}:00", "total": float(r["total"] or 0), "total_discounts": float(r["total_discounts"] or 0), "count": r["count"]}
            for r in rows
        ])


class HeldOrderViewSet(viewsets.ModelViewSet):
    queryset = (
        HeldOrder.objects
        .select_related("branch__company", "register", "cashier", "customer")
        .prefetch_related("items__product")
    )
    serializer_class = HeldOrderSerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        status_value = self.request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @action(detail=False, methods=["post"])
    def hold(self, request):
        serializer = HoldOrderSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data.pop("items")
        with transaction.atomic():
            held_order = HeldOrder.objects.create(**serializer.validated_data)
            for item in items:
                HeldOrderItem.objects.create(held_order=held_order, **item)
        return Response(HeldOrderSerializer(held_order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        held_order = self.get_object()
        held_order.status = HeldOrder.RESUMED
        held_order.save(update_fields=["status", "updated_at"])
        return Response(HeldOrderSerializer(held_order).data)

    @action(detail=True, methods=["put", "patch"], url_path="update-hold")
    def update_hold(self, request, pk=None):
        held_order = self.get_object()
        if held_order.status != HeldOrder.OPEN:
            raise ValidationError({"held_order": "Only open held orders can be updated."})
        serializer = UpdateHoldOrderSerializer(
            data=request.data, partial=True, context={"request": request, "held_order": held_order}
        )
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data.get("items")
        with transaction.atomic():
            if "customer" in serializer.validated_data:
                held_order.customer = serializer.validated_data["customer"]
            if "note" in serializer.validated_data:
                held_order.note = serializer.validated_data["note"]
            if items is not None:
                held_order.items.all().delete()
                for item in items:
                    HeldOrderItem.objects.create(held_order=held_order, **item)
            held_order.save()
        held_order = self.get_queryset().get(pk=held_order.pk)
        return Response(HeldOrderSerializer(held_order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        held_order = self.get_object()
        held_order.status = HeldOrder.CANCELLED
        held_order.save(update_fields=["status", "updated_at"])
        return Response(HeldOrderSerializer(held_order).data)
