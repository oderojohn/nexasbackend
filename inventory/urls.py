from django.urls import include, path
from rest_framework.routers import DefaultRouter

from pos.views import (
    CategoryViewSet,
    InventoryStockViewSet,
    ProductViewSet,
    PurchaseOrderViewSet,
    StockMovementViewSet,
    StocktakeViewSet,
    SupplierViewSet,
)


router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="inventory-categories")
router.register("products", ProductViewSet, basename="inventory-products")
router.register("stock", InventoryStockViewSet, basename="inventory-stock")
router.register("stock-movements", StockMovementViewSet, basename="inventory-stock-movements")
router.register("purchase-orders", PurchaseOrderViewSet, basename="inventory-purchase-orders")
router.register("stocktakes", StocktakeViewSet, basename="inventory-stocktakes")
router.register("suppliers", SupplierViewSet, basename="inventory-suppliers")

urlpatterns = [
    path("", include(router.urls)),
]
