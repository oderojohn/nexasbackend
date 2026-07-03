from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    AuditLog,
    Branch,
    CashTransaction,
    CreditRepayment,
    Customer,
    InventoryStock,
    LoyaltyTransaction,
    Payment,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceiptCopy,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    Shift,
    StockMovement,
    StocktakeItem,
    StocktakeSession,
    Register,
)


MONEY = Decimal("0.01")


def quantize_money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def next_receipt_no(branch, device_id=None):
    today = timezone.localdate().strftime("%Y%m%d")
    # Device-prefixed numbering prevents collisions between offline devices.
    # Online (server-generated): {BRANCH}-{DATE}-NNNN
    # Offline (device-generated): {BRANCH}-{DEV8}-{DATE}-NNNN
    if device_id:
        safe_dev = device_id[:8].replace("-", "").upper()
        prefix = f"{branch.code}-{safe_dev}-{today}-"
    else:
        prefix = f"{branch.code}-{today}-"
    latest = Sale.objects.filter(receipt_no__startswith=prefix).aggregate(value=Max("receipt_no"))["value"]
    next_number = 1
    if latest:
        try:
            next_number = int(latest.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            next_number = 1
    return f"{prefix}{next_number:04d}"


def next_sequence(model, field_name, prefix):
    latest = model.objects.filter(**{f"{field_name}__startswith": prefix}).aggregate(value=Max(field_name))["value"]
    next_number = 1
    if latest:
        next_number = int(latest.rsplit("-", 1)[1]) + 1
    return f"{prefix}{next_number:04d}"


def audit(*, user=None, action, entity="", entity_id="", branch=None, notes=""):
    return AuditLog.objects.create(user=user, action=action, entity=entity, entity_id=str(entity_id or ""), branch=branch, notes=notes)


def ensure_default_register(branch):
    """Ensure every branch has at least one active POS register."""
    register = Register.objects.filter(branch=branch, is_active=True).order_by("id").first()
    if register:
        return register
    existing_count = Register.objects.filter(branch=branch).count()
    code = f"POS-{(existing_count + 1):02d}"
    while Register.objects.filter(branch=branch, code=code).exists():
        existing_count += 1
        code = f"POS-{(existing_count + 1):02d}"
    return Register.objects.create(
        branch=branch,
        code=code,
        name=f"Counter {(existing_count + 1):02d}",
        is_active=True,
    )


def require_open_shift(shift):
    if shift.status != Shift.OPEN:
        raise ValidationError({"shift": "Sales can only be posted to an open shift."})


@transaction.atomic
def checkout_sale(*, cashier, branch, register, shift, customer=None, mode=Sale.RETAIL, items=None, payments=None, device_id=None, receipt_no=None, override_credit_limit=False):
    branch = Branch.objects.select_for_update().get(pk=branch.pk)
    shift = Shift.objects.select_for_update().get(pk=shift.pk)
    require_open_shift(shift)
    if shift.branch_id != branch.id or shift.register_id != register.id:
        raise ValidationError({"shift": "Shift does not belong to the selected branch and register."})

    items = items or []
    payments = payments or []
    if not items:
        raise ValidationError({"items": "At least one item is required."})
    if not payments:
        raise ValidationError({"payments": "At least one payment is required."})

    if receipt_no:
        if Sale.objects.filter(receipt_no=receipt_no).exists():
            raise ValidationError({"receipt_no": f"Receipt {receipt_no} already exists — duplicate sync upload."})
    else:
        receipt_no = next_receipt_no(branch, device_id=device_id)

    sale = Sale.objects.create(
        receipt_no=receipt_no,
        branch=branch,
        register=register,
        shift=shift,
        cashier=cashier,
        customer=customer,
        mode=mode,
        status=Sale.PAID,
        device_id=device_id or "",
    )

    subtotal = Decimal("0.00")
    discount_total = Decimal("0.00")
    tax_total = Decimal("0.00")

    for line in items:
        product = line["product"]
        quantity = int(line["quantity"])
        if quantity <= 0:
            raise ValidationError({"items": "Quantity must be greater than zero."})

        stock = InventoryStock.objects.select_for_update().get(branch=branch, product=product)
        if stock.quantity < quantity:
            raise ValidationError({"stock": f"Insufficient stock for {product.name}. Available: {stock.quantity}."})

        unit_price = quantize_money(product.wholesale_price if mode == Sale.WHOLESALE else product.retail_price)
        discount_amount = quantize_money(line.get("discount_amount", Decimal("0.00")))
        gross = unit_price * quantity
        taxable = max(Decimal("0.00"), gross - discount_amount)
        tax_amount = quantize_money(taxable * product.tax_rate / Decimal("100.00"))
        line_total = quantize_money(taxable + tax_amount)

        SaleItem.objects.create(
            sale=sale,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            discount_amount=discount_amount,
            tax_amount=tax_amount,
            line_total=line_total,
        )

        stock.quantity -= quantity
        stock.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            branch=branch,
            product=product,
            quantity_delta=-quantity,
            reason=StockMovement.SALE,
            reference=receipt_no,
            user=cashier,
        )

        subtotal += gross
        discount_total += discount_amount
        tax_total += tax_amount

    total = quantize_money(subtotal - discount_total + tax_total)
    paid_total = sum((quantize_money(payment["amount"]) for payment in payments), Decimal("0.00"))
    if paid_total < total - Decimal("0.01"):
        raise ValidationError({"payments": "Paid amount cannot be less than sale total."})

    credit_amount = sum(
        (quantize_money(payment["amount"]) for payment in payments if payment["method"] == Payment.CREDIT),
        Decimal("0.00"),
    )
    if credit_amount > 0:
        if not branch.credit_sale_enabled:
            raise ValidationError({"payments": "Credit sales are not enabled for this branch."})
        if not customer:
            raise ValidationError({"customer": "A customer is required for credit sales."})
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        if customer.credit_limit <= 0:
            raise ValidationError({"customer": "This customer does not have a credit limit set."})
        exceeds_limit = customer.credit_balance + credit_amount > customer.credit_limit
        if exceeds_limit and not override_credit_limit:
            raise ValidationError({"customer": "Customer has exceeded the available credit limit."})
        customer.credit_balance = quantize_money(customer.credit_balance + credit_amount)
        customer.save(update_fields=["credit_balance", "updated_at"])
        if exceeds_limit and override_credit_limit:
            audit(
                user=cashier, action="sale.credit_limit_override", entity="Customer", entity_id=customer.id,
                branch=branch, notes=f"Credit limit overridden for {customer.name}: balance {customer.credit_balance} vs limit {customer.credit_limit}",
            )

    for payment in payments:
        Payment.objects.create(
            sale=sale,
            method=payment["method"],
            amount=quantize_money(payment["amount"]),
            reference=payment.get("reference", ""),
        )

    sale.subtotal = quantize_money(subtotal)
    sale.discount_total = quantize_money(discount_total)
    sale.tax_total = quantize_money(tax_total)
    sale.total = total
    sale.paid_total = quantize_money(paid_total)
    sale.change_due = quantize_money(paid_total - total)
    sale.save()

    cash_paid = sum((payment.amount for payment in sale.payments.filter(method=Payment.CASH)), Decimal("0.00"))
    if cash_paid:
        shift.expected_cash = quantize_money(shift.expected_cash + cash_paid - sale.change_due)
        shift.save(update_fields=["expected_cash", "updated_at"])

    ReceiptCopy.objects.create(sale=sale, printed_by=cashier, copy_no=1)
    audit(user=cashier, action="sale.checkout", entity="Sale", entity_id=sale.id, branch=branch, notes=receipt_no)
    return sale


@transaction.atomic
def void_sale(*, sale, user, reason):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status == Sale.VOIDED:
        raise ValidationError({"sale": "Sale is already voided."})
    if sale.status != Sale.PAID:
        raise ValidationError({"sale": "Only paid sales can be voided."})
    if not reason:
        raise ValidationError({"reason": "Void reason is required."})

    for item in sale.items.select_related("product"):
        stock = InventoryStock.objects.select_for_update().get(branch=sale.branch, product=item.product)
        stock.quantity += item.quantity
        stock.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            branch=sale.branch,
            product=item.product,
            quantity_delta=item.quantity,
            reason=StockMovement.VOID,
            reference=sale.receipt_no,
            user=user,
        )

    cash_paid = sum((payment.amount for payment in sale.payments.filter(method=Payment.CASH)), Decimal("0.00"))
    if cash_paid:
        sale.shift.expected_cash = quantize_money(sale.shift.expected_cash - cash_paid + sale.change_due)
        sale.shift.save(update_fields=["expected_cash", "updated_at"])

    if sale.customer_id:
        credit_paid = sum((payment.amount for payment in sale.payments.filter(method=Payment.CREDIT)), Decimal("0.00"))
        if credit_paid:
            customer = Customer.objects.select_for_update().get(pk=sale.customer_id)
            customer.credit_balance = quantize_money(max(Decimal("0.00"), customer.credit_balance - credit_paid))
            customer.save(update_fields=["credit_balance", "updated_at"])

    earned_points = sum(
        (t.points for t in LoyaltyTransaction.objects.filter(sale=sale, transaction_type=LoyaltyTransaction.EARN)),
        0,
    )
    if earned_points:
        customer = Customer.objects.select_for_update().get(pk=sale.customer_id)
        customer.loyalty_points = max(0, customer.loyalty_points - earned_points)
        customer.save(update_fields=["loyalty_points", "updated_at"])
        LoyaltyTransaction.objects.create(
            customer=customer, branch=sale.branch, points=-earned_points,
            transaction_type=LoyaltyTransaction.ADJUSTMENT, sale=sale, recorded_by=user,
            notes=f"Reversed on void of {sale.receipt_no}",
        )

    sale.status = Sale.VOIDED
    sale.voided_at = timezone.now()
    sale.voided_by = user
    sale.void_reason = reason
    sale.save(update_fields=["status", "voided_at", "voided_by", "void_reason", "updated_at"])
    audit(user=user, action="sale.void", entity="Sale", entity_id=sale.id, branch=sale.branch, notes=reason)
    return sale


@transaction.atomic
def record_credit_repayment(*, customer, amount, recorded_by, method=CreditRepayment.CASH, reference="", shift=None, notes=""):
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    amount = quantize_money(amount)
    if amount <= 0:
        raise ValidationError({"amount": "Amount must be greater than zero."})
    if amount > customer.credit_balance:
        raise ValidationError({"amount": "Amount cannot exceed the outstanding balance."})
    customer.credit_balance = quantize_money(customer.credit_balance - amount)
    customer.save(update_fields=["credit_balance", "updated_at"])
    repayment = CreditRepayment.objects.create(
        customer=customer, branch=customer.branch, shift=shift, amount=amount,
        method=method, reference=reference, recorded_by=recorded_by, notes=notes,
    )
    if method == CreditRepayment.CASH and shift is not None:
        shift.expected_cash = quantize_money(shift.expected_cash + amount)
        shift.save(update_fields=["expected_cash", "updated_at"])
    audit(
        user=recorded_by, action="customer.settle_credit", entity="Customer", entity_id=customer.id,
        branch=customer.branch, notes=f"Recorded repayment of {amount} for {customer.name} via {method}",
    )
    return repayment


@transaction.atomic
def award_loyalty_points(*, customer, sale_amount, recorded_by, branch, sale=None):
    from .admin_settings import get_or_create_company_settings

    if not branch.loyalty_enabled:
        raise ValidationError({"branch": "Loyalty points are not enabled for this branch."})
    settings_obj = get_or_create_company_settings(branch.company)
    policy = settings_obj.merged_settings()["credit_loyalty"]
    sale_amount = quantize_money(sale_amount)
    minimum_purchase = Decimal(str(policy.get("loyalty_minimum_purchase_amount") or 0))
    if sale_amount < minimum_purchase:
        raise ValidationError({"sale_amount": f"A minimum purchase of {minimum_purchase} is required to earn points."})
    if branch.loyalty_points_rate <= 0:
        raise ValidationError({"branch": "Loyalty earn rate is not configured for this branch."})

    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    points_earned = int(sale_amount // branch.loyalty_points_rate)
    if points_earned <= 0:
        raise ValidationError({"sale_amount": "Sale amount is too small to earn any points."})
    customer.loyalty_points = customer.loyalty_points + points_earned
    customer.save(update_fields=["loyalty_points", "updated_at"])
    LoyaltyTransaction.objects.create(
        customer=customer, branch=branch, points=points_earned,
        transaction_type=LoyaltyTransaction.EARN, sale=sale, recorded_by=recorded_by,
    )
    return points_earned, customer.loyalty_points


@transaction.atomic
def redeem_loyalty_points(*, customer, points, recorded_by, branch):
    from .admin_settings import get_or_create_company_settings

    settings_obj = get_or_create_company_settings(branch.company)
    policy = settings_obj.merged_settings()["credit_loyalty"]
    minimum_points = int(policy.get("loyalty_minimum_points_redemption") or 0)
    redemption_rate = Decimal(str(policy.get("loyalty_redemption_rate") or 0))
    if points <= 0:
        raise ValidationError({"points": "Points must be greater than zero."})
    if points < minimum_points:
        raise ValidationError({"points": f"A minimum of {minimum_points} points is required to redeem."})

    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if points > customer.loyalty_points:
        raise ValidationError({"points": "Customer does not have enough loyalty points."})
    customer.loyalty_points = customer.loyalty_points - points
    customer.save(update_fields=["loyalty_points", "updated_at"])
    LoyaltyTransaction.objects.create(
        customer=customer, branch=branch, points=-points,
        transaction_type=LoyaltyTransaction.REDEEM, recorded_by=recorded_by,
    )
    value = quantize_money(Decimal(points) * redemption_rate)
    return value, customer.loyalty_points


@transaction.atomic
def adjust_loyalty_points(*, customer, points_delta, recorded_by, reason):
    if points_delta == 0:
        raise ValidationError({"points_delta": "Adjustment cannot be zero."})
    if not reason:
        raise ValidationError({"reason": "A reason is required for manual adjustments."})
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    new_balance = customer.loyalty_points + points_delta
    if new_balance < 0:
        raise ValidationError({"points_delta": "Adjustment would make the balance negative."})
    customer.loyalty_points = new_balance
    customer.save(update_fields=["loyalty_points", "updated_at"])
    LoyaltyTransaction.objects.create(
        customer=customer, branch=customer.branch, points=points_delta,
        transaction_type=LoyaltyTransaction.ADJUSTMENT, recorded_by=recorded_by, notes=reason,
    )
    return customer.loyalty_points


@transaction.atomic
def close_shift(*, shift, counted_cash):
    shift = Shift.objects.select_for_update().get(pk=shift.pk)
    if shift.status != Shift.OPEN:
        raise ValidationError({"shift": "Shift is already closed."})

    counted = quantize_money(counted_cash)
    shift.counted_cash = counted
    shift.cash_variance = quantize_money(counted - shift.expected_cash)
    shift.closed_at = timezone.now()
    shift.status = Shift.CLOSED
    shift.save()
    return shift


@transaction.atomic
def reprint_receipt(*, sale, user):
    last_copy = sale.receipt_copies.aggregate(value=Max("copy_no"))["value"] or 0
    copy = ReceiptCopy.objects.create(sale=sale, printed_by=user, copy_no=last_copy + 1)
    audit(user=user, action="receipt.reprint", entity="Sale", entity_id=sale.id, branch=sale.branch, notes=sale.receipt_no)
    return copy


@transaction.atomic
def create_purchase_order(*, branch, supplier, items, created_by=None, expected_at=None):
    if not items:
        raise ValidationError({"items": "At least one purchase order item is required."})
    if not str(supplier or "").strip():
        raise ValidationError({"supplier": "Supplier is required."})
    product_ids = [item["product"].id for item in items]
    if len(product_ids) != len(set(product_ids)):
        raise ValidationError({"items": "Duplicate products are not allowed on the same purchase order."})
    po = PurchaseOrder.objects.create(
        po_no=next_sequence(PurchaseOrder, "po_no", f"PO-{timezone.localdate().strftime('%Y%m%d')}-"),
        branch=branch,
        supplier=supplier,
        created_by=created_by,
        expected_at=expected_at,
        status=PurchaseOrder.ORDERED,
    )
    total = Decimal("0.00")
    for item in items:
        quantity = int(item["ordered_quantity"])
        unit_cost = quantize_money(item.get("unit_cost", Decimal("0.00")))
        if quantity <= 0:
            raise ValidationError({"ordered_quantity": f"Quantity must be greater than zero for {item['product'].name}."})
        if unit_cost < 0:
            raise ValidationError({"unit_cost": f"Buying price cannot be negative for {item['product'].name}."})
        PurchaseOrderItem.objects.create(
            purchase_order=po,
            product=item["product"],
            ordered_quantity=quantity,
            unit_cost=unit_cost,
        )
        total += unit_cost * quantity
    po.total = quantize_money(total)
    po.save(update_fields=["total", "updated_at"])
    audit(user=created_by, action="purchase_order.create", entity="PurchaseOrder", entity_id=po.id, branch=branch, notes=po.po_no)
    return po


@transaction.atomic
def cancel_purchase_order(*, purchase_order, user=None, reason=""):
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if purchase_order.status == PurchaseOrder.CANCELLED:
        raise ValidationError({"purchase_order": "This purchase order is already cancelled."})
    if purchase_order.status in [PurchaseOrder.RECEIVED, PurchaseOrder.PARTIAL]:
        raise ValidationError({"purchase_order": "Received or partially-received orders cannot be cancelled."})
    purchase_order.status = PurchaseOrder.CANCELLED
    purchase_order.save(update_fields=["status", "updated_at"])
    audit(user=user, action="purchase_order.cancel", entity="PurchaseOrder", entity_id=purchase_order.id, branch=purchase_order.branch, notes=reason or purchase_order.po_no)
    return purchase_order


@transaction.atomic
def update_purchase_order(*, purchase_order, supplier, items, expected_at=None, user=None):
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if purchase_order.status in [PurchaseOrder.RECEIVED, PurchaseOrder.CANCELLED]:
        raise ValidationError({"purchase_order": "Received or cancelled orders cannot be edited."})

    if not str(supplier or "").strip():
        raise ValidationError({"supplier": "Supplier is required."})

    product_ids = [item["product"].id for item in items]
    if len(product_ids) != len(set(product_ids)):
        raise ValidationError({"items": "Duplicate products are not allowed on the same purchase order."})

    if not items:
        raise ValidationError({"items": "At least one line item is required."})

    purchase_order.supplier = supplier
    purchase_order.expected_at = expected_at
    purchase_order.save(update_fields=["supplier", "expected_at", "updated_at"])

    purchase_order.items.all().delete()
    total = Decimal("0.00")
    for item in items:
        quantity = int(item["ordered_quantity"])
        unit_cost = quantize_money(item.get("unit_cost", Decimal("0.00")))
        if quantity <= 0:
            raise ValidationError({"ordered_quantity": f"Quantity must be greater than zero for {item['product'].name}."})
        if unit_cost < 0:
            raise ValidationError({"unit_cost": f"Cost cannot be negative for {item['product'].name}."})
        PurchaseOrderItem.objects.create(
            purchase_order=purchase_order,
            product=item["product"],
            ordered_quantity=quantity,
            unit_cost=unit_cost,
        )
        total += unit_cost * quantity
    purchase_order.total = quantize_money(total)
    purchase_order.save(update_fields=["total", "updated_at"])
    audit(user=user, action="purchase_order.update", entity="PurchaseOrder", entity_id=purchase_order.id, branch=purchase_order.branch, notes=purchase_order.po_no)
    return purchase_order


@transaction.atomic
def receive_purchase_order(*, purchase_order, items, user=None):
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if purchase_order.status in [PurchaseOrder.RECEIVED, PurchaseOrder.CANCELLED]:
        raise ValidationError({"purchase_order": "This purchase order cannot receive more stock."})
    if not items:
        raise ValidationError({"items": "At least one received item is required."})

    received_any = False
    for line in items:
        try:
            po_item = PurchaseOrderItem.objects.select_for_update().get(pk=line["item"].pk, purchase_order=purchase_order)
        except PurchaseOrderItem.DoesNotExist:
            raise ValidationError({"items": "Received item does not belong to the selected purchase order."})
        received_now = int(line["received_quantity"])
        if received_now < 0:
            raise ValidationError({"received_quantity": f"Received quantity cannot be negative for {po_item.product.name}."})
        if po_item.received_quantity + received_now > po_item.ordered_quantity:
            raise ValidationError({"received_quantity": f"Received quantity exceeds ordered quantity for {po_item.product.name}."})
        if received_now == 0:
            continue
        received_any = True
        stock, _ = InventoryStock.objects.select_for_update().get_or_create(
            branch=purchase_order.branch,
            product=po_item.product,
            defaults={"quantity": 0},
        )
        stock.quantity += received_now
        stock.save(update_fields=["quantity", "updated_at"])
        po_item.received_quantity += received_now
        po_item.save(update_fields=["received_quantity"])
        if po_item.unit_cost != po_item.product.cost_price:
            po_item.product.cost_price = po_item.unit_cost
            po_item.product.save(update_fields=["cost_price", "updated_at"])
        StockMovement.objects.create(
            branch=purchase_order.branch,
            product=po_item.product,
            quantity_delta=received_now,
            reason=StockMovement.RECEIVE,
            reference=purchase_order.po_no,
            user=user,
        )

    if not received_any:
        raise ValidationError({"received_quantity": "Enter a received quantity greater than zero for at least one item."})

    all_items = list(purchase_order.items.all())
    if all(item.received_quantity >= item.ordered_quantity for item in all_items):
        purchase_order.status = PurchaseOrder.RECEIVED
    elif any(item.received_quantity > 0 for item in all_items):
        purchase_order.status = PurchaseOrder.PARTIAL
    purchase_order.save(update_fields=["status", "updated_at"])
    audit(user=user, action="purchase_order.receive", entity="PurchaseOrder", entity_id=purchase_order.id, branch=purchase_order.branch, notes=purchase_order.po_no)
    return purchase_order


@transaction.atomic
def adjust_stock(*, branch, product, quantity_delta, reason, user=None):
    stock, _ = InventoryStock.objects.select_for_update().get_or_create(branch=branch, product=product, defaults={"quantity": 0})
    new_quantity = stock.quantity + int(quantity_delta)
    if new_quantity < 0:
        raise ValidationError({"quantity_delta": "Adjustment cannot make stock negative."})
    stock.quantity = new_quantity
    stock.save(update_fields=["quantity", "updated_at"])
    StockMovement.objects.create(branch=branch, product=product, quantity_delta=quantity_delta, reason=StockMovement.ADJUSTMENT, reference=reason, user=user)
    audit(user=user, action="stock.adjust", entity="Product", entity_id=product.id, branch=branch, notes=reason)
    return stock


@transaction.atomic
def create_stocktake(*, branch, created_by=None, note=""):
    session = StocktakeSession.objects.create(
        session_no=next_sequence(StocktakeSession, "session_no", f"ST-{timezone.localdate().strftime('%Y%m%d')}-"),
        branch=branch,
        created_by=created_by,
        note=note,
    )
    for stock in InventoryStock.objects.filter(branch=branch).select_related("product"):
        StocktakeItem.objects.create(stocktake=session, product=stock.product, system_quantity=stock.quantity, counted_quantity=stock.quantity)
    audit(user=created_by, action="stocktake.create", entity="StocktakeSession", entity_id=session.id, branch=branch, notes=session.session_no)
    return session


@transaction.atomic
def count_stocktake(*, stocktake, items):
    stocktake = StocktakeSession.objects.select_for_update().get(pk=stocktake.pk)
    if stocktake.status not in [StocktakeSession.OPEN, StocktakeSession.COUNTED]:
        raise ValidationError({"stocktake": "Only open stocktakes can be counted."})
    for line in items:
        item = StocktakeItem.objects.select_for_update().get(pk=line["item"].pk, stocktake=stocktake)
        item.counted_quantity = int(line["counted_quantity"])
        item.save(update_fields=["counted_quantity"])
    stocktake.status = StocktakeSession.COUNTED
    stocktake.save(update_fields=["status", "updated_at"])
    return stocktake


@transaction.atomic
def approve_stocktake(*, stocktake, user=None):
    stocktake = StocktakeSession.objects.select_for_update().get(pk=stocktake.pk)
    if stocktake.status == StocktakeSession.APPROVED:
        raise ValidationError({"stocktake": "Stocktake is already approved."})
    if stocktake.status == StocktakeSession.CANCELLED:
        raise ValidationError({"stocktake": "Cancelled stocktakes cannot be approved."})
    # Enforce FIFO approval order by created_at within the branch
    earlier_pending = StocktakeSession.objects.exclude(status=StocktakeSession.APPROVED).filter(
        branch=stocktake.branch,
        created_at__lt=stocktake.created_at,
    )
    if earlier_pending.exists():
        earlier_ids = list(earlier_pending.values_list("session_no", flat=True)[:3])
        raise ValidationError({
            "stocktake": (
                f"Sessions must be approved in order. Please approve older session(s) first: "
                + ", ".join(earlier_ids)
                + (" …" if earlier_pending.count() > 3 else "")
                + "."
            )
        })
    for item in stocktake.items.select_related("product"):
        delta = item.counted_quantity - item.system_quantity
        if delta:
            adjust_stock(branch=stocktake.branch, product=item.product, quantity_delta=delta, reason=stocktake.session_no, user=user)
    stocktake.status = StocktakeSession.APPROVED
    stocktake.approved_by = user
    stocktake.approved_at = timezone.now()
    stocktake.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    audit(user=user, action="stocktake.approve", entity="StocktakeSession", entity_id=stocktake.id, branch=stocktake.branch, notes=stocktake.session_no)
    return stocktake


def _returned_quantity_for_product(sale, product_id, exclude_return_id=None):
    qs = SaleReturnItem.objects.filter(
        sale_return__sale=sale,
        sale_return__status=SaleReturn.COMPLETED,
        product_id=product_id,
    )
    if exclude_return_id:
        qs = qs.exclude(sale_return_id=exclude_return_id)
    return sum(item.quantity for item in qs)


def _sale_line_for_product(sale, product):
    return sale.items.filter(product=product).first()


@transaction.atomic
def create_sale_return(*, sale, processed_by, reason, items, refund_method=Payment.CASH, shift=None):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.PAID:
        raise ValidationError({"sale": "Only paid sales can be returned."})
    if not reason:
        raise ValidationError({"reason": "Return reason is required."})
    if not items:
        raise ValidationError({"items": "At least one return item is required."})

    branch = sale.branch
    if shift and shift.branch_id != branch.id:
        raise ValidationError({"shift": "Shift must belong to the sale branch."})

    subtotal_refund = Decimal("0.00")
    tax_refund = Decimal("0.00")
    return_no = next_sequence(SaleReturn, "return_no", f"RET-{timezone.localdate().strftime('%Y%m%d')}-")
    sale_return = SaleReturn.objects.create(
        return_no=return_no,
        sale=sale,
        branch=branch,
        shift=shift or sale.shift,
        processed_by=processed_by,
        reason=reason,
        refund_method=refund_method,
    )

    for line in items:
        product = line["product"]
        quantity = int(line["quantity"])
        if quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})
        sale_line = _sale_line_for_product(sale, product)
        if not sale_line:
            raise ValidationError({"product": f"{product.name} was not on the original sale."})
        already_returned = _returned_quantity_for_product(sale, product.id)
        remaining = sale_line.quantity - already_returned
        if quantity > remaining:
            raise ValidationError({
                "quantity": f"Cannot return {quantity} of {product.name}. Remaining returnable quantity: {remaining}."
            })
        unit_price = quantize_money(sale_line.unit_price)
        gross = unit_price * quantity
        discount_share = quantize_money(
            (sale_line.discount_amount / sale_line.quantity) * quantity if sale_line.quantity else Decimal("0.00")
        )
        taxable = max(Decimal("0.00"), gross - discount_share)
        tax_amount = quantize_money(taxable * product.tax_rate / Decimal("100.00"))
        line_refund = quantize_money(taxable + tax_amount)
        SaleReturnItem.objects.create(
            sale_return=sale_return,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            line_refund=line_refund,
        )
        subtotal_refund += gross - discount_share
        tax_refund += tax_amount

    sale_return.subtotal_refund = quantize_money(subtotal_refund)
    sale_return.tax_refund = quantize_money(tax_refund)
    sale_return.total_refund = quantize_money(subtotal_refund + tax_refund)
    sale_return.save(update_fields=["subtotal_refund", "tax_refund", "total_refund", "updated_at"])
    audit(
        user=processed_by,
        action="sale_return.create",
        entity="SaleReturn",
        entity_id=sale_return.id,
        branch=branch,
        notes=return_no,
    )
    return sale_return


@transaction.atomic
def approve_sale_return(*, sale_return, user):
    sale_return = SaleReturn.objects.select_for_update().get(pk=sale_return.pk)
    if sale_return.status != SaleReturn.PENDING:
        raise ValidationError({"sale_return": "Only pending returns can be approved."})
    sale_return.status = SaleReturn.APPROVED
    sale_return.approved_by = user
    sale_return.approved_at = timezone.now()
    sale_return.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    audit(user=user, action="sale_return.approve", entity="SaleReturn", entity_id=sale_return.id, branch=sale_return.branch, notes=sale_return.return_no)
    return sale_return


@transaction.atomic
def reject_sale_return(*, sale_return, user, reason=""):
    sale_return = SaleReturn.objects.select_for_update().get(pk=sale_return.pk)
    if sale_return.status != SaleReturn.PENDING:
        raise ValidationError({"sale_return": "Only pending returns can be rejected."})
    sale_return.status = SaleReturn.REJECTED
    sale_return.approved_by = user
    sale_return.rejection_reason = reason or "Rejected"
    sale_return.rejected_at = timezone.now()
    sale_return.save(update_fields=["status", "approved_by", "rejection_reason", "rejected_at", "updated_at"])
    audit(user=user, action="sale_return.reject", entity="SaleReturn", entity_id=sale_return.id, branch=sale_return.branch, notes=reason or sale_return.return_no)
    return sale_return


@transaction.atomic
def complete_sale_return(*, sale_return, user):
    sale_return = SaleReturn.objects.select_for_update().select_related("sale", "shift").get(pk=sale_return.pk)
    if sale_return.status not in [SaleReturn.PENDING, SaleReturn.APPROVED]:
        raise ValidationError({"sale_return": "Only pending or approved returns can be completed."})

    for item in sale_return.items.select_related("product"):
        stock = InventoryStock.objects.select_for_update().get(branch=sale_return.branch, product=item.product)
        stock.quantity += item.quantity
        stock.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            branch=sale_return.branch,
            product=item.product,
            quantity_delta=item.quantity,
            reason=StockMovement.RETURN,
            reference=sale_return.return_no,
            user=user,
        )

    if sale_return.refund_method == Payment.CASH and sale_return.shift_id:
        shift = Shift.objects.select_for_update().get(pk=sale_return.shift_id)
        shift.expected_cash = quantize_money(shift.expected_cash - sale_return.total_refund)
        shift.save(update_fields=["expected_cash", "updated_at"])

    sale_return.status = SaleReturn.COMPLETED
    sale_return.completed_at = timezone.now()
    if not sale_return.approved_by_id:
        sale_return.approved_by = user
        sale_return.approved_at = timezone.now()
    sale_return.save(update_fields=["status", "completed_at", "approved_by", "approved_at", "updated_at"])
    audit(user=user, action="sale_return.complete", entity="SaleReturn", entity_id=sale_return.id, branch=sale_return.branch, notes=sale_return.return_no)
    return sale_return


@transaction.atomic
def record_cash_transaction(*, shift, branch, transaction_type, amount, user=None, reason="", reference=""):
    shift = Shift.objects.select_for_update().get(pk=shift.pk)
    if shift.status != Shift.OPEN:
        raise ValidationError({"shift": "Cash transactions can only be recorded on open shifts."})
    if shift.branch_id != branch.id:
        raise ValidationError({"branch": "Shift must belong to the selected branch."})

    value = quantize_money(amount)
    if value <= 0:
        raise ValidationError({"amount": "Amount must be greater than zero."})

    if transaction_type == CashTransaction.CASH_IN:
        shift.expected_cash = quantize_money(shift.expected_cash + value)
    else:
        if shift.expected_cash < value:
            raise ValidationError({"amount": "Insufficient expected cash for this transaction."})
        shift.expected_cash = quantize_money(shift.expected_cash - value)
    shift.save(update_fields=["expected_cash", "updated_at"])

    cash_tx = CashTransaction.objects.create(
        shift=shift,
        branch=branch,
        transaction_type=transaction_type,
        amount=value,
        reason=reason,
        reference=reference,
        user=user,
    )
    audit(
        user=user,
        action=f"cash.{transaction_type}",
        entity="CashTransaction",
        entity_id=cash_tx.id,
        branch=branch,
        notes=reason or reference,
    )
    return cash_tx
