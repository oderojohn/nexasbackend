"""POS notification feed — live-state only, no history logs."""
from django.db.models import F
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DiscountRule, InventoryStock, PriceSchedule


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pos_notifications(request):
    """
    Returns live-state notifications for the POS bell:
      - Currently active discount rules
      - Upcoming (unapplied) price schedules
      - Low-stock products (0 < quantity <= reorder_point)
      - Out-of-stock products (quantity == 0)
    """
    branch_id = request.query_params.get('branch')
    if not branch_id:
        return Response({'notifications': [], 'count': 0})

    now = timezone.now()
    notifications = []

    # ── Active discount rules ─────────────────────────────────────────────────
    for rule in (
        DiscountRule.objects
        .filter(branch_id=branch_id, is_active=True)
        .select_related('category', 'product')
    ):
        if not rule.is_active_now():
            continue
        val_str = f'{rule.value}%' if rule.discount_type == 'percent' else f'Ksh {rule.value}'
        target = rule.target.replace('_', ' ') if rule.target else 'all products'
        suffix = ''
        if rule.end_date:
            suffix = f' · ends {rule.end_date}'
        notifications.append({
            'id': f'rule-{rule.id}',
            'type': 'discount_active',
            'title': rule.name,
            'body': f'{val_str} on {target}{suffix}',
            'severity': 'success',
        })

    # ── Upcoming price schedules ──────────────────────────────────────────────
    for sched in (
        PriceSchedule.objects
        .filter(branch_id=branch_id, is_applied=False)
        .select_related('product')
        .order_by('effective_at')[:20]
    ):
        parts = []
        if sched.new_retail_price is not None:
            parts.append(f'Retail → Ksh {sched.new_retail_price}')
        if sched.new_wholesale_price is not None:
            parts.append(f'Wholesale → Ksh {sched.new_wholesale_price}')
        eff = sched.effective_at.strftime('%d %b, %H:%M') if sched.effective_at else 'manual'
        product_name = sched.product.name if sched.product_id else 'Unknown'
        notifications.append({
            'id': f'sched-{sched.id}',
            'type': 'price_scheduled',
            'title': product_name,
            'body': f'{", ".join(parts)} · {eff}',
            'severity': 'info',
        })

    # ── Low stock ─────────────────────────────────────────────────────────────
    for row in (
        InventoryStock.objects
        .filter(
            branch_id=branch_id,
            product__is_active=True,
            quantity__gt=0,
            quantity__lte=F('product__reorder_point'),
        )
        .select_related('product')
        .order_by('quantity', 'product__name')[:20]
    ):
        unit = 'unit' if row.quantity == 1 else 'units'
        notifications.append({
            'id': f'lowstock-{row.product_id}',
            'type': 'low_stock',
            'title': row.product.name,
            'body': f'{row.quantity} {unit} left (reorder at {row.product.reorder_point})',
            'severity': 'warning',
        })

    # ── Out of stock ──────────────────────────────────────────────────────────
    for row in (
        InventoryStock.objects
        .filter(branch_id=branch_id, product__is_active=True, quantity__lte=0)
        .select_related('product')
        .order_by('product__name')[:20]
    ):
        notifications.append({
            'id': f'outofstock-{row.product_id}',
            'type': 'out_of_stock',
            'title': row.product.name,
            'body': 'Out of stock — restock needed',
            'severity': 'error',
        })

    return Response({'notifications': notifications, 'count': len(notifications)})
