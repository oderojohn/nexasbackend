from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from pos.models import (
    Branch,
    Category,
    Customer,
    HeldOrder,
    InventoryStock,
    Payment,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceiptCopy,
    Register,
    Sale,
    SaleItem,
    Shift,
    StockMovement,
    StocktakeItem,
    StocktakeSession,
    UserProfile,
)


class Command(BaseCommand):
    help = "Seed a usable POS demo database."

    def handle(self, *args, **options):
        user_model = get_user_model()
        cashier, _ = user_model.objects.get_or_create(username="cashier", defaults={"is_staff": True})
        cashier.set_password("cashier123")
        cashier.save()

        branch, _ = Branch.objects.get_or_create(code="MAIN", defaults={"name": "Main Branch", "location": "Nairobi CBD"})
        register, _ = Register.objects.get_or_create(branch=branch, code="POS-02", defaults={"name": "Counter 02"})
        UserProfile.objects.update_or_create(user=cashier, defaults={"pin": "1234", "role": UserProfile.ADMIN, "branch": branch, "is_active": True})

        ReceiptCopy.objects.all().delete()
        Payment.objects.all().delete()
        SaleItem.objects.all().delete()
        Sale.objects.all().delete()
        Shift.objects.all().delete()
        HeldOrder.objects.all().delete()
        PurchaseOrderItem.objects.all().delete()
        PurchaseOrder.objects.all().delete()
        StocktakeItem.objects.all().delete()
        StocktakeSession.objects.all().delete()
        StockMovement.objects.all().delete()
        InventoryStock.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()

        categories = {
            "Beverages": [
                {
                    "name": "Coke 500ml",
                    "sku": "BEV-001",
                    "barcode": "616100000001",
                    "retail_price": Decimal("120.00"),
                    "wholesale_price": Decimal("100.00"),
                    "cost_price": Decimal("75.00"),
                    "stock": 40,
                },
                {
                    "name": "Fanta 500ml",
                    "sku": "BEV-002",
                    "barcode": "616100000002",
                    "retail_price": Decimal("110.00"),
                    "wholesale_price": Decimal("95.00"),
                    "cost_price": Decimal("68.00"),
                    "stock": 38,
                },
                {
                    "name": "Mineral Water 1L",
                    "sku": "BEV-003",
                    "barcode": "616100000003",
                    "retail_price": Decimal("90.00"),
                    "wholesale_price": Decimal("75.00"),
                    "cost_price": Decimal("50.00"),
                    "stock": 45,
                },
                {
                    "name": "Fresh Juice 330ml",
                    "sku": "BEV-004",
                    "barcode": "616100000004",
                    "retail_price": Decimal("150.00"),
                    "wholesale_price": Decimal("130.00"),
                    "cost_price": Decimal("95.00"),
                    "stock": 28,
                },
            ],
            "Groceries": [
                {
                    "name": "Premium Rice 5kg",
                    "sku": "GRO-001",
                    "barcode": "616100000005",
                    "retail_price": Decimal("980.00"),
                    "wholesale_price": Decimal("900.00"),
                    "cost_price": Decimal("780.00"),
                    "stock": 25,
                },
                {
                    "name": "Cooking Oil 2L",
                    "sku": "GRO-002",
                    "barcode": "616100000006",
                    "retail_price": Decimal("560.00"),
                    "wholesale_price": Decimal("520.00"),
                    "cost_price": Decimal("430.00"),
                    "stock": 30,
                },
                {
                    "name": "Sugar 2kg",
                    "sku": "GRO-003",
                    "barcode": "616100000007",
                    "retail_price": Decimal("320.00"),
                    "wholesale_price": Decimal("290.00"),
                    "cost_price": Decimal("220.00"),
                    "stock": 32,
                },
                {
                    "name": "Maize Flour 2kg",
                    "sku": "GRO-004",
                    "barcode": "616100000008",
                    "retail_price": Decimal("280.00"),
                    "wholesale_price": Decimal("245.00"),
                    "cost_price": Decimal("190.00"),
                    "stock": 30,
                },
            ],
            "Snacks": [
                {
                    "name": "Potato Chips 100g",
                    "sku": "SNK-001",
                    "barcode": "616100000009",
                    "retail_price": Decimal("130.00"),
                    "wholesale_price": Decimal("110.00"),
                    "cost_price": Decimal("80.00"),
                    "stock": 34,
                },
                {
                    "name": "Chocolate Bar 50g",
                    "sku": "SNK-002",
                    "barcode": "616100000010",
                    "retail_price": Decimal("140.00"),
                    "wholesale_price": Decimal("120.00"),
                    "cost_price": Decimal("90.00"),
                    "stock": 29,
                },
                {
                    "name": "Soda Biscuits 200g",
                    "sku": "SNK-003",
                    "barcode": "616100000011",
                    "retail_price": Decimal("170.00"),
                    "wholesale_price": Decimal("145.00"),
                    "cost_price": Decimal("110.00"),
                    "stock": 26,
                },
                {
                    "name": "Nuts Mix 150g",
                    "sku": "SNK-004",
                    "barcode": "616100000012",
                    "retail_price": Decimal("220.00"),
                    "wholesale_price": Decimal("195.00"),
                    "cost_price": Decimal("150.00"),
                    "stock": 20,
                },
            ],
            "Household": [
                {
                    "name": "Bath Soap 100g",
                    "sku": "HH-001",
                    "barcode": "616100000013",
                    "retail_price": Decimal("110.00"),
                    "wholesale_price": Decimal("95.00"),
                    "cost_price": Decimal("60.00"),
                    "stock": 40,
                },
                {
                    "name": "Laundry Powder 1kg",
                    "sku": "HH-002",
                    "barcode": "616100000014",
                    "retail_price": Decimal("320.00"),
                    "wholesale_price": Decimal("285.00"),
                    "cost_price": Decimal("220.00"),
                    "stock": 27,
                },
                {
                    "name": "Dishwashing Liquid 500ml",
                    "sku": "HH-003",
                    "barcode": "616100000015",
                    "retail_price": Decimal("210.00"),
                    "wholesale_price": Decimal("185.00"),
                    "cost_price": Decimal("140.00"),
                    "stock": 33,
                },
                {
                    "name": "Bleach 1L",
                    "sku": "HH-004",
                    "barcode": "616100000016",
                    "retail_price": Decimal("180.00"),
                    "wholesale_price": Decimal("155.00"),
                    "cost_price": Decimal("110.00"),
                    "stock": 30,
                },
            ],
            "Personal Care": [
                {
                    "name": "Toothpaste 125ml",
                    "sku": "PC-001",
                    "barcode": "616100000017",
                    "retail_price": Decimal("210.00"),
                    "wholesale_price": Decimal("185.00"),
                    "cost_price": Decimal("140.00"),
                    "stock": 31,
                },
                {
                    "name": "Shampoo 250ml",
                    "sku": "PC-002",
                    "barcode": "616100000018",
                    "retail_price": Decimal("280.00"),
                    "wholesale_price": Decimal("245.00"),
                    "cost_price": Decimal("180.00"),
                    "stock": 28,
                },
                {
                    "name": "Hand Sanitizer 200ml",
                    "sku": "PC-003",
                    "barcode": "616100000019",
                    "retail_price": Decimal("190.00"),
                    "wholesale_price": Decimal("165.00"),
                    "cost_price": Decimal("110.00"),
                    "stock": 35,
                },
                {
                    "name": "Body Lotion 200ml",
                    "sku": "PC-004",
                    "barcode": "616100000020",
                    "retail_price": Decimal("360.00"),
                    "wholesale_price": Decimal("320.00"),
                    "cost_price": Decimal("240.00"),
                    "stock": 24,
                },
            ],
        }

        branch_qs = Branch.objects.filter(is_active=True).order_by("id")
        branch_count = branch_qs.count()

        for branch_item in branch_qs:
            for category_name, product_rows in categories.items():
                category = Category.objects.create(branch=branch_item, name=category_name)
                for row in product_rows:
                    product_data = row.copy()
                    stock_quantity = product_data.pop("stock")
                    product = Product.objects.create(
                        branch=branch_item,
                        category=category,
                        tax_rate=Decimal("16.00"),
                        reorder_point=10,
                        **product_data,
                    )
                    InventoryStock.objects.create(branch=branch_item, product=product, quantity=stock_quantity)

        for name in ["Walk-in Customer", "Brian Mwangi", "Mary Wanjiku", "Nairobi Cafe Ltd"]:
            Customer.objects.get_or_create(name=name)

        self.stdout.write(self.style.SUCCESS("Seeded POS demo data."))
        self.stdout.write(f"Cashier: {cashier.username} / cashier123 / PIN 1234")
        self.stdout.write(f"Branch: {branch.id}, Register: {register.id}")
        self.stdout.write(f"Catalogue: 5 categories, 20 products per active branch ({branch_count} branch(es)).")
