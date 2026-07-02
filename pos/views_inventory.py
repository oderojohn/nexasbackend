"""Inventory stock, stock movements and stocktake viewsets."""
import datetime

from django.db.models import Count, F, Sum as DbSum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    InventoryStock,
    Product,
    StockMovement,
    StocktakeSession,
)
from .serializers import (
    ApproveStocktakeSerializer,
    CountStocktakeSerializer,
    CreateStocktakeSerializer,
    InventoryStockSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    StocktakeSessionSerializer,
)
from .services import adjust_stock, approve_stocktake, count_stocktake, create_stocktake
from .views_helpers import (
    _csv_response,
    _filter_branch_scoped_queryset,
    _pdf_response,
    _resolve_read_branch,
)


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _prev_month_str(ym):
    year, month = int(ym[:4]), int(ym[5:7])
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    return f"{prev_year:04d}-{prev_month:02d}"


class InventoryStockViewSet(viewsets.ModelViewSet):
    queryset = InventoryStock.objects.select_related("branch__company", "product")
    serializer_class = InventoryStockSerializer

    def get_queryset(self):
        return _filter_branch_scoped_queryset(super().get_queryset(), self.request)

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        serializer = StockAdjustmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        stock = adjust_stock(**serializer.validated_data)
        return Response(InventoryStockSerializer(stock).data)

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        rows = self.get_queryset().filter(
            product__is_active=True,
            quantity__lte=F("product__reorder_point"),
        )
        return Response(InventoryStockSerializer(rows, many=True).data)

    @action(detail=False, methods=["get"], url_path="stock-valuation")
    def stock_valuation(self, request):
        branch = _resolve_read_branch(request)
        qs = InventoryStock.objects.select_related("branch__company", "product__category").filter(
            product__is_active=True,
        )
        if branch:
            qs = qs.filter(branch=branch)

        category_id = request.query_params.get("category")
        if category_id:
            qs = qs.filter(product__category_id=category_id)

        start_date = _parse_iso_date(request.query_params.get("start_date"))
        end_date = _parse_iso_date(request.query_params.get("end_date"))
        if start_date:
            qs = qs.filter(updated_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(updated_at__date__lte=end_date)

        export_format = request.query_params.get("export")
        rows_data = []
        total_cost = total_retail = total_wholesale = 0

        for stock in qs.prefetch_related("product__category"):
            product = stock.product
            category_name = getattr(getattr(product, "category", None), "name", "—")
            cost, retail, wholesale = product.cost_price, product.retail_price, product.wholesale_price
            qty = stock.quantity
            value_cost, value_retail, value_wholesale = cost * qty, retail * qty, wholesale * qty
            total_cost += value_cost
            total_retail += value_retail
            total_wholesale += value_wholesale
            rows_data.append({
                "product_id": product.id, "product_name": product.name, "sku": product.sku,
                "category": category_name, "branch": stock.branch.code, "quantity": qty,
                "cost_price": str(cost), "retail_price": str(retail), "wholesale_price": str(wholesale),
                "value_at_cost": str(value_cost), "value_at_retail": str(value_retail),
                "value_at_wholesale": str(value_wholesale),
            })

        if export_format == "csv":
            csv_rows = [
                [r["product_name"], r["sku"], r["category"], r["branch"], r["quantity"],
                 r["cost_price"], r["value_at_cost"], r["retail_price"],
                 r["value_at_retail"], r["wholesale_price"], r["value_at_wholesale"]]
                for r in rows_data
            ]
            return _csv_response(
                "stock_valuation.csv",
                ["Product", "SKU", "Category", "Branch", "Quantity", "Cost Price",
                 "Value @ Cost", "Retail Price", "Value @ Retail", "Wholesale Price", "Value @ Wholesale"],
                csv_rows,
            )
        if export_format == "pdf":
            pdf_rows = [[r["product_name"], r["sku"], r["category"], r["branch"], r["quantity"], r["value_at_cost"]] for r in rows_data]
            return _pdf_response("stock_valuation.pdf", "Stock Valuation Report",
                                 ["Product", "SKU", "Category", "Branch", "Qty", "Value @ Cost"], pdf_rows)
        return Response({
            "rows": rows_data,
            "summary": {
                "item_count": len(rows_data),
                "total_cost_value": str(total_cost),
                "total_retail_value": str(total_retail),
                "total_wholesale_value": str(total_wholesale),
            },
        })

    @action(detail=False, methods=["get"], url_path="fast-slow-moving")
    def fast_slow_moving(self, request):
        branch = _resolve_read_branch(request)
        days = int(request.query_params.get("days") or 30)
        start_dt = timezone.now() - datetime.timedelta(days=days)

        base_qs = StockMovement.objects.filter(
            created_at__gte=start_dt,
            reason__in=[StockMovement.SALE, StockMovement.RECEIVE, StockMovement.ADJUSTMENT],
        ).select_related("product", "product__category")
        if branch:
            base_qs = base_qs.filter(branch=branch)

        category_id = request.query_params.get("category")
        if category_id:
            base_qs = base_qs.filter(product__category_id=category_id)

        product_stats = {}
        for entry in base_qs.values("product_id").annotate(movement_count=Count("id"), total_qty=DbSum("quantity_delta")):
            product_stats[entry["product_id"]] = {
                "movement_count": entry["movement_count"], "total_qty": entry["total_qty"],
            }

        products_qs = Product.objects.filter(is_active=True)
        if branch:
            products_qs = products_qs.filter(branch=branch)
        if category_id:
            products_qs = products_qs.filter(category_id=category_id)
        products = list(products_qs.select_related("category").prefetch_related("stock_rows"))

        # Build stock lookup from prefetch cache — .filter() inside the loop bypasses it and fires N queries
        stock_map = {}
        for p in products:
            for row in p.stock_rows.all():
                stock_map[(p.id, row.branch_id)] = row.quantity

        export_format = request.query_params.get("export")
        moving_data = []
        for product in products:
            stats = product_stats.get(product.id, {"movement_count": 0, "total_qty": 0})
            fast_qty = abs(stats["total_qty"]) if stats["total_qty"] else 0
            category_name = getattr(product.category, "name", "—")
            current_stock = stock_map.get((product.id, branch.id), 0) if branch else 0
            moving_data.append({
                "product_id": product.id, "product_name": product.name, "sku": product.sku,
                "category": category_name, "movement_count": stats["movement_count"],
                "total_qty_in_out": fast_qty, "current_stock": current_stock,
                "movement_type": "fast" if stats["movement_count"] > 0 else "static",
            })

        counts = [d["movement_count"] for d in moving_data]
        avg_count = (sum(counts) / len(counts)) if counts else 0
        fast_items = sorted(
            [d for d in moving_data if d["movement_count"] >= avg_count and d["movement_count"] > 0],
            key=lambda x: x["movement_count"], reverse=True,
        )
        slow_items = sorted(
            [d for d in moving_data if d["movement_count"] < avg_count],
            key=lambda x: x["movement_count"],
        )

        if export_format == "csv":
            header = ["Product", "SKU", "Category", "Movement Count", "Total Qty In/Out", "Current Stock", "Type"]
            csv_rows = [
                [d["product_name"], d["sku"], d["category"], d["movement_count"],
                 d["total_qty_in_out"], d["current_stock"],
                 "Fast-moving" if d["movement_type"] == "fast" else "Slow/Static"]
                for d in moving_data
            ]
            return _csv_response("fast_slow_moving.csv", header, csv_rows)
        if export_format == "pdf":
            pdf_rows = [[d["product_name"], d["sku"], d["category"], d["movement_count"], d["total_qty_in_out"]] for d in moving_data]
            return _pdf_response("fast_slow_moving.pdf", "Fast/Slow Moving Report",
                                 ["Product", "SKU", "Category", "Moves", "Qty"], pdf_rows)
        return Response({
            "period_days": days,
            "average_movement_per_product": round(avg_count, 2),
            "fast_moving": fast_items,
            "slow_moving": slow_items,
        })

    @action(detail=False, methods=["get"], url_path="monthly-variance")
    def monthly_variance(self, request):
        branch = _resolve_read_branch(request)
        year = int(request.query_params.get("year") or timezone.now().year)
        month = request.query_params.get("month")
        export_format = request.query_params.get("export")

        products_qs = Product.objects.filter(is_active=True)
        if branch:
            products_qs = products_qs.filter(branch=branch)
        products = list(products_qs.select_related("category"))

        qs = InventoryStock.objects.select_related("product", "branch").filter(product__in=products)
        if branch:
            qs = qs.filter(branch=branch)
        stock_map = {stock.product_id: stock.quantity for stock in qs}

        stocktake_qs = StocktakeSession.objects.filter(status=StocktakeSession.APPROVED)
        if branch:
            stocktake_qs = stocktake_qs.filter(branch=branch)
        if month:
            try:
                month_int = int(month)
            except ValueError:
                month_int = None
            if month_int:
                stocktake_qs = stocktake_qs.filter(created_at__year=year, created_at__month=month_int)
        else:
            stocktake_qs = stocktake_qs.filter(created_at__year=year)
        stocktake_qs = stocktake_qs.select_related("branch").prefetch_related("items__product")

        monthly_snapshots = {}
        for session in stocktake_qs:
            for item in session.items.all():
                m = session.created_at.strftime("%Y-%m")
                monthly_snapshots.setdefault(m, {})[item.product_id] = item.counted_quantity

        all_months = sorted(monthly_snapshots.keys())
        period = month or (all_months[-1] if all_months else f"{year}-01")
        target_months = [period] if month else all_months

        reports = []
        for product in products:
            category_name = getattr(product.category, "name", "—")
            closing_qty = stock_map.get(product.id, 0)
            row = {"product_id": product.id, "product_name": product.name, "sku": product.sku, "category": category_name}
            for m in target_months:
                snap = monthly_snapshots.get(m, {}).get(product.id)
                row[f"closing_stock_{m}"] = snap if snap is not None else closing_qty
            if len(target_months) == 2:
                c1 = row.get(f"closing_stock_{target_months[0]}", 0) or 0
                c2 = row.get(f"closing_stock_{target_months[1]}", 0) or 0
                row["variance"] = (c1 or 0) - (c2 or 0)
            elif len(target_months) == 1 and product.id in monthly_snapshots.get(target_months[0], {}):
                row["variance"] = 0
            else:
                row["variance"] = None
            reports.append(row)

        if export_format == "csv":
            if len(target_months) == 2:
                header = ["Product", "SKU", "Category",
                          f"Closing Stock {target_months[0]}", f"Closing Stock {target_months[1]}", "Variance"]
                csv_rows = [
                    [r["product_name"], r["sku"], r["category"],
                     r.get(f"closing_stock_{target_months[0]}", 0),
                     r.get(f"closing_stock_{target_months[1]}", 0),
                     r.get("variance") if r.get("variance") is not None else "—"]
                    for r in reports
                ]
            else:
                header = ["Product", "SKU", "Category", "Period", "Closing Stock", "Variance"]
                csv_rows = [
                    [r["product_name"], r["sku"], r["category"], target_months[0],
                     r.get(f"closing_stock_{target_months[0]}", 0),
                     r.get("variance") if r.get("variance") is not None else "—"]
                    for r in reports
                ]
            return _csv_response("monthly_variance.csv", header, csv_rows)
        if export_format == "pdf":
            pdf_rows = [[r["product_name"], r["sku"], r["category"],
                         r.get("variance") if r.get("variance") is not None else "—"] for r in reports]
            return _pdf_response("monthly_variance.pdf", "Monthly Variance Report",
                                 ["Product", "SKU", "Category", "Variance"], pdf_rows)
        return Response({
            "year": year, "months": target_months, "rows": reports,
            "monthly_snapshots_count": len(monthly_snapshots),
        })


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related("branch__company", "product", "user")
    serializer_class = StockMovementSerializer

    def get_queryset(self):
        qs = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        p = self.request.query_params
        if p.get("product"):
            qs = qs.filter(product_id=p["product"])
        if p.get("reason"):
            qs = qs.filter(reason=p["reason"])
        if p.get("date_from"):
            qs = qs.filter(created_at__date__gte=p["date_from"])
        if p.get("date_to"):
            qs = qs.filter(created_at__date__lte=p["date_to"])
        return qs


class StocktakeViewSet(viewsets.ModelViewSet):
    queryset = (
        StocktakeSession.objects
        .select_related("branch__company", "created_by", "approved_by")
        .prefetch_related("items__product")
    )
    serializer_class = StocktakeSessionSerializer

    def get_queryset(self):
        return _filter_branch_scoped_queryset(super().get_queryset(), self.request)

    @action(detail=False, methods=["post"])
    def start(self, request):
        serializer = CreateStocktakeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        session = create_stocktake(**serializer.validated_data)
        return Response(StocktakeSessionSerializer(session).data, status=201)

    @action(detail=True, methods=["post"])
    def count(self, request, pk=None):
        serializer = CountStocktakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = count_stocktake(stocktake=self.get_object(), **serializer.validated_data)
        return Response(StocktakeSessionSerializer(session).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        serializer = ApproveStocktakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = approve_stocktake(stocktake=self.get_object(), **serializer.validated_data)
        return Response(StocktakeSessionSerializer(session).data)
