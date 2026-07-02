"""
Scheduled report management: CRUD for ReportSchedule + email sending logic.
SMTP credentials are loaded from CompanySettings.email_config at send time,
not from Django settings — so admins can configure email from the UI.
"""
import datetime
from decimal import Decimal

from django.core.mail import get_connection, EmailMultiAlternatives
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import Payment, ReportSchedule, Sale, SaleItem, SaleReturn, Shift
from .permissions import user_can_access_branch
from .serializers import ReportScheduleSerializer
from .views_helpers import (
    _filter_branch_scoped_queryset,
    _resolve_read_branch,
    is_branch_admin,
)


# ---------------------------------------------------------------------------
# Permission helper
# ---------------------------------------------------------------------------

def _can_manage_schedules(user):
    return is_branch_admin(user)


# ---------------------------------------------------------------------------
# Report data assembly
# ---------------------------------------------------------------------------

def _date_range_for_type(report_type, reference_date=None):
    """Return (start_dt, end_dt, label) for the report period."""
    today = reference_date or timezone.localdate()
    if report_type == ReportSchedule.DAILY:
        start = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time.min)
        end = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time.max)
        label = (today - datetime.timedelta(days=1)).strftime("%A, %d %B %Y")
    elif report_type == ReportSchedule.WEEKLY:
        week_end = today - datetime.timedelta(days=1)
        week_start = week_end - datetime.timedelta(days=6)
        start = datetime.datetime.combine(week_start, datetime.time.min)
        end = datetime.datetime.combine(week_end, datetime.time.max)
        label = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"
    else:  # MONTHLY
        first_of_this_month = today.replace(day=1)
        last_month_end = first_of_this_month - datetime.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        start = datetime.datetime.combine(last_month_start, datetime.time.min)
        end = datetime.datetime.combine(last_month_end, datetime.time.max)
        label = last_month_start.strftime("%B %Y")
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(start, tz),
        timezone.make_aware(end, tz),
        label,
    )


def _build_report_data(schedule, start_dt, end_dt):
    branch = schedule.branch
    currency = branch.company.currency if branch.company else "KES"

    sales_qs = Sale.objects.filter(
        branch=branch,
        status="paid",
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    )

    agg = sales_qs.aggregate(
        total_sales=Sum("subtotal"),
        total_discount=Sum("discount_total"),
        total_tax=Sum("tax_total"),
        tx_count=Count("id"),
    )
    total_sales = agg["total_sales"] or Decimal("0")
    total_discount = agg["total_discount"] or Decimal("0")
    total_tax = agg["total_tax"] or Decimal("0")
    tx_count = agg["tx_count"] or 0

    # Gross profit: sum of (unit_price - cost_price) * quantity for all sold items
    gross_profit = Decimal("0")
    if schedule.include_gross_profit:
        items = SaleItem.objects.filter(
            sale__branch=branch,
            sale__status="paid",
            sale__created_at__gte=start_dt,
            sale__created_at__lte=end_dt,
        ).select_related("product")
        for item in items:
            cost = item.product.cost_price or Decimal("0")
            gross_profit += (item.unit_price - cost - (item.discount_amount or Decimal("0"))) * item.quantity

    # Payment method breakdown
    payment_breakdown = []
    if schedule.include_payment_methods:
        payments = (
            Payment.objects.filter(
                sale__branch=branch,
                sale__status="paid",
                sale__created_at__gte=start_dt,
                sale__created_at__lte=end_dt,
            )
            .values("method")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )
        payment_breakdown = list(payments)

    # Per-cashier breakdown
    cashier_rows = []
    if schedule.include_cashier_breakdown:
        cashier_agg = (
            sales_qs.values("cashier__username", "cashier__first_name", "cashier__last_name")
            .annotate(sales=Sum("subtotal"), tx=Count("id"))
            .order_by("-sales")
        )
        # Cash variance per cashier (from shifts)
        shift_variance = {}
        shifts = Shift.objects.filter(
            branch=branch,
            opened_at__gte=start_dt,
            closed_at__lte=end_dt,
            status="closed",
        )
        for shift in shifts:
            name = shift.cashier.username
            variance = (shift.counted_cash or Decimal("0")) - (shift.expected_cash or Decimal("0"))
            shift_variance[name] = shift_variance.get(name, Decimal("0")) + variance

        for row in cashier_agg:
            username = row["cashier__username"] or "Unknown"
            first = row["cashier__first_name"] or ""
            last = row["cashier__last_name"] or ""
            display = f"{first} {last}".strip() or username
            cashier_rows.append({
                "name": display,
                "username": username,
                "sales": row["sales"] or Decimal("0"),
                "tx": row["tx"] or 0,
                "variance": shift_variance.get(username, Decimal("0")),
            })

    # Top products
    top_products = []
    if schedule.include_top_products:
        top = (
            SaleItem.objects.filter(
                sale__branch=branch,
                sale__status="paid",
                sale__created_at__gte=start_dt,
                sale__created_at__lte=end_dt,
            )
            .values("product__name")
            .annotate(qty=Sum("quantity"), revenue=Sum("unit_price"))
            .order_by("-revenue")[:10]
        )
        top_products = list(top)

    # Returns
    returns_total = Decimal("0")
    returns_count = 0
    if schedule.include_returns:
        ret_agg = SaleReturn.objects.filter(
            branch=branch,
            status="completed",
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        ).aggregate(total=Sum("total_refund"), count=Count("id"))
        returns_total = ret_agg["total"] or Decimal("0")
        returns_count = ret_agg["count"] or 0

    return {
        "currency": currency,
        "total_sales": total_sales,
        "total_discount": total_discount,
        "total_tax": total_tax,
        "tx_count": tx_count,
        "gross_profit": gross_profit,
        "payment_breakdown": payment_breakdown,
        "cashier_rows": cashier_rows,
        "top_products": top_products,
        "returns_total": returns_total,
        "returns_count": returns_count,
    }


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

def _fmt(currency, value):
    try:
        return f"{currency} {float(value):,.2f}"
    except Exception:
        return f"{currency} 0.00"


def _build_html_email(schedule, period_label, data):
    branch = schedule.branch
    company = branch.company
    currency = data["currency"]

    def row(label, value, color="#1e293b"):
        return f"""
        <tr>
          <td style="padding:8px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9">{label}</td>
          <td style="padding:8px 16px;font-size:13px;font-weight:600;color:{color};text-align:right;border-bottom:1px solid #f1f5f9">{value}</td>
        </tr>"""

    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;background:#f8fafc;padding:24px">
      <div style="background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.08);overflow:hidden">

        <!-- Header -->
        <div style="background:linear-gradient(135deg,#059669,#047857);padding:28px 32px">
          <p style="margin:0;font-size:11px;font-weight:700;color:#a7f3d0;letter-spacing:.08em;text-transform:uppercase">
            {schedule.get_report_type_display()} Sales Report
          </p>
          <h1 style="margin:4px 0 0;font-size:22px;font-weight:800;color:#fff">{branch.name}</h1>
          <p style="margin:4px 0 0;font-size:13px;color:#d1fae5">{company.name if company else ''} · {period_label}</p>
        </div>

        <!-- Key metrics -->
        <div style="padding:24px 32px">
          <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;border:1px solid #e2e8f0;overflow:hidden">
            {row("Total Sales", _fmt(currency, data["total_sales"]), "#059669")}
            {row("Transactions", str(data["tx_count"]))}
            {row("Discounts Given", _fmt(currency, data["total_discount"]), "#d97706")}
            {row("Tax Collected", _fmt(currency, data["total_tax"]))}
            {(row("Gross Profit", _fmt(currency, data["gross_profit"]), "#2563eb") if schedule.include_gross_profit else "")}
          </table>
        </div>
    """

    # Payment methods
    if schedule.include_payment_methods and data["payment_breakdown"]:
        rows_html = "".join(
            row(p["method"].replace("_", " ").title(), _fmt(currency, p["total"]))
            for p in data["payment_breakdown"]
        )
        body += f"""
        <div style="padding:0 32px 24px">
          <h2 style="font-size:14px;font-weight:700;color:#1e293b;margin:0 0 12px">Payment Methods</h2>
          <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;border:1px solid #e2e8f0;overflow:hidden">
            {rows_html}
          </table>
        </div>"""

    # Per-cashier breakdown
    if schedule.include_cashier_breakdown and data["cashier_rows"]:
        cashier_html = ""
        for c in data["cashier_rows"]:
            variance_color = "#059669" if c["variance"] >= 0 else "#dc2626"
            variance_sign = "+" if c["variance"] >= 0 else ""
            cashier_html += f"""
            <tr>
              <td style="padding:8px 16px;font-size:13px;color:#1e293b;border-bottom:1px solid #f1f5f9">{c["name"]}</td>
              <td style="padding:8px 16px;font-size:13px;text-align:right;border-bottom:1px solid #f1f5f9">{_fmt(currency, c["sales"])}</td>
              <td style="padding:8px 16px;font-size:13px;text-align:right;border-bottom:1px solid #f1f5f9">{c["tx"]}</td>
              <td style="padding:8px 16px;font-size:13px;font-weight:600;text-align:right;color:{variance_color};border-bottom:1px solid #f1f5f9">{variance_sign}{_fmt(currency, c["variance"])}</td>
            </tr>"""
        body += f"""
        <div style="padding:0 32px 24px">
          <h2 style="font-size:14px;font-weight:700;color:#1e293b;margin:0 0 12px">Cashier Breakdown</h2>
          <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;border:1px solid #e2e8f0;overflow:hidden">
            <thead>
              <tr style="background:#f8fafc">
                <th style="padding:8px 16px;font-size:11px;font-weight:700;color:#64748b;text-align:left;text-transform:uppercase;letter-spacing:.05em">Cashier</th>
                <th style="padding:8px 16px;font-size:11px;font-weight:700;color:#64748b;text-align:right;text-transform:uppercase;letter-spacing:.05em">Sales</th>
                <th style="padding:8px 16px;font-size:11px;font-weight:700;color:#64748b;text-align:right;text-transform:uppercase;letter-spacing:.05em">Txns</th>
                <th style="padding:8px 16px;font-size:11px;font-weight:700;color:#64748b;text-align:right;text-transform:uppercase;letter-spacing:.05em">Cash Variance</th>
              </tr>
            </thead>
            <tbody>{cashier_html}</tbody>
          </table>
        </div>"""

    # Top products
    if schedule.include_top_products and data["top_products"]:
        prod_html = "".join(
            row(p["product__name"], _fmt(currency, p["revenue"]))
            for p in data["top_products"]
        )
        body += f"""
        <div style="padding:0 32px 24px">
          <h2 style="font-size:14px;font-weight:700;color:#1e293b;margin:0 0 12px">Top Products</h2>
          <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;border:1px solid #e2e8f0;overflow:hidden">
            {prod_html}
          </table>
        </div>"""

    # Returns
    if schedule.include_returns and data["returns_count"] > 0:
        body += f"""
        <div style="padding:0 32px 24px">
          <h2 style="font-size:14px;font-weight:700;color:#1e293b;margin:0 0 12px">Returns & Refunds</h2>
          <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;border:1px solid #e2e8f0;overflow:hidden">
            {row("Total Refunds", _fmt(currency, data["returns_total"]), "#dc2626")}
            {row("Refund Transactions", str(data["returns_count"]))}
          </table>
        </div>"""

    body += f"""
        <!-- Footer -->
        <div style="padding:20px 32px;border-top:1px solid #f1f5f9;text-align:center">
          <p style="margin:0;font-size:11px;color:#94a3b8">
            Nexa POS · {branch.name} · Automated {schedule.get_report_type_display()} Report
          </p>
        </div>
      </div>
    </div>"""

    return body


# ---------------------------------------------------------------------------
# Send helper
# ---------------------------------------------------------------------------

def _get_email_connection(branch):
    """Build a live SMTP connection from CompanySettings stored in the DB."""
    from .admin_settings import get_or_create_company_settings
    from .models import default_company_settings
    company = branch.company
    if not company:
        raise ValueError("Branch has no associated company.")
    settings_obj = get_or_create_company_settings(company)
    defaults = default_company_settings().get("email_config", {})
    cfg = {**defaults, **(settings_obj.email_config or {})}
    host = cfg.get("host", "")
    if not host:
        raise ValueError(
            "SMTP host is not configured. Go to Administration → Scheduled Reports → Email Settings."
        )
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=host,
        port=int(cfg.get("port", 587)),
        username=cfg.get("username", ""),
        password=cfg.get("password", ""),
        use_tls=bool(cfg.get("use_tls", True)),
        fail_silently=False,
    ), cfg


def send_report(schedule, reference_date=None):
    """Build and send the email report for the given schedule. Returns True on success."""
    if not schedule.recipients:
        return False

    connection, cfg = _get_email_connection(schedule.branch)
    from_name = cfg.get("from_name", "Nexa POS")
    from_addr = cfg.get("from_email", "") or cfg.get("username", "noreply@nexapos.com")
    from_header = f"{from_name} <{from_addr}>" if from_name else from_addr

    start_dt, end_dt, period_label = _date_range_for_type(schedule.report_type, reference_date)
    data = _build_report_data(schedule, start_dt, end_dt)
    html = _build_html_email(schedule, period_label, data)

    subject = f"[{schedule.get_report_type_display()} Report] {schedule.branch.name} — {period_label}"
    msg = EmailMultiAlternatives(
        subject=subject,
        body=(
            f"Sales Report for {schedule.branch.name}: {period_label}. "
            f"Total Sales: {_fmt(data['currency'], data['total_sales'])}, "
            f"Transactions: {data['tx_count']}."
        ),
        from_email=from_header,
        to=schedule.recipients,
        connection=connection,
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)

    schedule.last_sent_at = timezone.now()
    schedule.save(update_fields=["last_sent_at"])
    return True


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------

class ReportScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = ReportScheduleSerializer

    def get_queryset(self):
        return _filter_branch_scoped_queryset(
            ReportSchedule.objects.select_related("branch", "branch__company"),
            self.request,
        )

    def _check_permission(self):
        if not _can_manage_schedules(self.request.user):
            raise PermissionDenied("Branch admin or higher required to manage report schedules.")

    def _check_branch_access(self, branch):
        if branch and not user_can_access_branch(self.request.user, branch):
            raise PermissionDenied("You do not have access to this branch.")

    def perform_create(self, serializer):
        self._check_permission()
        branch = serializer.validated_data.get("branch")
        self._check_branch_access(branch)
        if ReportSchedule.objects.filter(
            branch=branch,
            report_type=serializer.validated_data.get("report_type"),
        ).exists():
            raise ValidationError({"report_type": "A schedule of this type already exists for this branch."})
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._check_permission()
        branch = serializer.validated_data.get("branch")
        self._check_branch_access(branch)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_permission()
        instance.delete()

    @action(detail=True, methods=["post"], url_path="send-now")
    def send_now(self, request, pk=None):
        self._check_permission()
        schedule = self.get_object()
        if not schedule.recipients:
            return Response(
                {"detail": "No recipients configured."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            send_report(schedule)
            return Response({"detail": "Report sent successfully."})
        except Exception as exc:
            return Response(
                {"detail": f"Failed to send report: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="by-branch")
    def by_branch(self, request):
        """Return all three schedule types for the active branch, creating defaults as needed."""
        branch = _resolve_read_branch(request)
        if not branch:
            return Response({"detail": "No active branch."}, status=status.HTTP_400_BAD_REQUEST)

        schedules = {}
        for report_type, _ in ReportSchedule.REPORT_TYPE_CHOICES:
            obj, _ = ReportSchedule.objects.get_or_create(
                branch=branch,
                report_type=report_type,
                defaults={
                    "send_hour": 23,
                    "send_minute": 0,
                    "send_day_of_week": 0 if report_type == ReportSchedule.WEEKLY else None,
                    "send_day_of_month": 1 if report_type == ReportSchedule.MONTHLY else None,
                    "created_by": request.user,
                },
            )
            schedules[report_type] = ReportScheduleSerializer(obj).data

        return Response(schedules)
