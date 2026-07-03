"""Credit and loyalty reports — all branch-scoped, no backing model of their own."""
from datetime import timedelta

from django.db.models import Min
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import CreditRepayment, Customer, LoyaltyTransaction, Payment, Sale
from .views_helpers import _resolve_read_branch


def _date_filtered(queryset, request, field="created_at"):
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        queryset = queryset.filter(**{f"{field}__date__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{field}__date__lte": date_to})
    return queryset


class CreditLoyaltyReportsViewSet(viewsets.ViewSet):

    def _branch(self, request):
        branch = _resolve_read_branch(request)
        return branch

    @action(detail=False, methods=["get"], url_path="credit-balance")
    def credit_balance(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        rows = [
            {
                "customer_id": c.id, "name": c.name, "phone": c.phone,
                "credit_limit": c.credit_limit, "credit_balance": c.credit_balance,
                "available": max(c.credit_limit - c.credit_balance, 0),
            }
            for c in Customer.objects.filter(branch=branch).order_by("name")
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="outstanding-credit")
    def outstanding_credit(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        rows = [
            {
                "customer_id": c.id, "name": c.name, "phone": c.phone,
                "credit_limit": c.credit_limit, "credit_balance": c.credit_balance,
            }
            for c in Customer.objects.filter(branch=branch, credit_balance__gt=0).order_by("-credit_balance")
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="credit-payment-history")
    def credit_payment_history(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        qs = _date_filtered(CreditRepayment.objects.filter(branch=branch).select_related("customer", "recorded_by"), request)
        shift_id = request.query_params.get("shift")
        if shift_id:
            qs = qs.filter(shift_id=shift_id)
        rows = [
            {
                "id": r.id, "customer_name": r.customer.name, "customer_phone": r.customer.phone,
                "amount": r.amount, "method": r.method, "reference": r.reference,
                "recorded_by": r.recorded_by.username if r.recorded_by else "", "created_at": r.created_at,
            }
            for r in qs.order_by("-created_at")[:500]
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="credit-sales")
    def credit_sales(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        qs = _date_filtered(
            Payment.objects.filter(method=Payment.CREDIT, sale__branch=branch, sale__status=Sale.PAID).select_related("sale", "sale__customer"),
            request, field="created_at",
        )
        rows = [
            {
                "sale_id": p.sale_id, "receipt_no": p.sale.receipt_no,
                "customer_name": p.sale.customer.name if p.sale.customer else "—",
                "amount": p.amount, "created_at": p.created_at,
            }
            for p in qs.order_by("-created_at")[:500]
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="overdue-credit")
    def overdue_credit(self, request):
        from .admin_settings import get_or_create_company_settings

        branch = self._branch(request)
        if not branch:
            return Response([])
        due_days = int(get_or_create_company_settings(branch.company).merged_settings()["credit_loyalty"].get("credit_due_period_days") or 30)
        cutoff = timezone.now() - timedelta(days=due_days)
        customers = Customer.objects.filter(branch=branch, credit_balance__gt=0)
        rows = []
        for customer in customers:
            oldest = (
                Payment.objects.filter(method=Payment.CREDIT, sale__customer=customer, sale__status=Sale.PAID)
                .aggregate(oldest=Min("created_at"))["oldest"]
            )
            if oldest and oldest < cutoff:
                rows.append({
                    "customer_id": customer.id, "name": customer.name, "phone": customer.phone,
                    "credit_balance": customer.credit_balance, "oldest_credit_sale": oldest,
                    "days_overdue": (timezone.now() - oldest).days - due_days,
                })
        rows.sort(key=lambda r: r["days_overdue"], reverse=True)
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="loyalty-earned")
    def loyalty_earned(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        qs = _date_filtered(
            LoyaltyTransaction.objects.filter(branch=branch, transaction_type=LoyaltyTransaction.EARN).select_related("customer"),
            request,
        )
        rows = [
            {"id": t.id, "customer_name": t.customer.name, "points": t.points, "created_at": t.created_at}
            for t in qs.order_by("-created_at")[:500]
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="loyalty-redeemed")
    def loyalty_redeemed(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        qs = _date_filtered(
            LoyaltyTransaction.objects.filter(branch=branch, transaction_type=LoyaltyTransaction.REDEEM).select_related("customer"),
            request,
        )
        rows = [
            {"id": t.id, "customer_name": t.customer.name, "points": -t.points, "created_at": t.created_at}
            for t in qs.order_by("-created_at")[:500]
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="loyalty-balance")
    def loyalty_balance(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        rows = [
            {"customer_id": c.id, "name": c.name, "phone": c.phone, "loyalty_points": c.loyalty_points}
            for c in Customer.objects.filter(branch=branch).order_by("-loyalty_points")
        ]
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="top-loyalty-customers")
    def top_loyalty_customers(self, request):
        branch = self._branch(request)
        if not branch:
            return Response([])
        limit = int(request.query_params.get("limit", 20))
        rows = [
            {"customer_id": c.id, "name": c.name, "phone": c.phone, "loyalty_points": c.loyalty_points}
            for c in Customer.objects.filter(branch=branch, loyalty_points__gt=0).order_by("-loyalty_points")[:limit]
        ]
        return Response(rows)
