from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Branch, Category, Company, InventoryStock, Payment, Product, ReceiptCopy, Register, Sale, SaleReturn, Shift, StocktakeSession, UserProfile
from .rbac import permissions_for_profile
from .services import approve_stocktake, checkout_sale, complete_sale_return, create_purchase_order, create_sale_return, create_stocktake, receive_purchase_order, reprint_receipt, void_sale


class PosRuleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cashier", password="pass")
        self.company = Company.objects.create(name="Main Company", code="MAIN")
        self.branch = Branch.objects.create(company=self.company, code="MAIN", name="Main Branch")
        self.register = Register.objects.create(branch=self.branch, code="POS-01", name="Counter 01")
        self.category = Category.objects.create(branch=self.branch, name="Beers")
        self.product = Product.objects.create(
            branch=self.branch,
            category=self.category,
            name="Tusker Lager",
            sku="BEER-001",
            retail_price=Decimal("200.00"),
            wholesale_price=Decimal("180.00"),
            tax_rate=Decimal("0.00"),
        )
        self.stock = InventoryStock.objects.create(branch=self.branch, product=self.product, quantity=10)
        self.shift = Shift.objects.create(
            branch=self.branch,
            register=self.register,
            cashier=self.user,
            opening_cash=Decimal("1000.00"),
            expected_cash=Decimal("1000.00"),
        )

    def test_checkout_decrements_stock_and_records_payment(self):
        sale = checkout_sale(
            cashier=self.user,
            branch=self.branch,
            register=self.register,
            shift=self.shift,
            mode=Sale.RETAIL,
            items=[{"product": self.product, "quantity": 2}],
            payments=[{"method": Payment.CASH, "amount": Decimal("400.00")}],
        )

        self.stock.refresh_from_db()
        self.shift.refresh_from_db()
        self.assertEqual(sale.status, Sale.PAID)
        self.assertEqual(sale.total, Decimal("400.00"))
        self.assertEqual(self.stock.quantity, 8)
        self.assertEqual(self.shift.expected_cash, Decimal("1400.00"))

    def test_void_restores_stock(self):
        sale = checkout_sale(
            cashier=self.user,
            branch=self.branch,
            register=self.register,
            shift=self.shift,
            mode=Sale.RETAIL,
            items=[{"product": self.product, "quantity": 2}],
            payments=[{"method": Payment.CASH, "amount": Decimal("400.00")}],
        )

        void_sale(sale=sale, user=self.user, reason="Wrong item")
        self.stock.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.VOIDED)
        self.assertEqual(self.stock.quantity, 10)

    def test_reprint_increments_copy_number(self):
        sale = checkout_sale(
            cashier=self.user,
            branch=self.branch,
            register=self.register,
            shift=self.shift,
            mode=Sale.RETAIL,
            items=[{"product": self.product, "quantity": 1}],
            payments=[{"method": Payment.CASH, "amount": Decimal("200.00")}],
        )

        copy = reprint_receipt(sale=sale, user=self.user)
        self.assertEqual(ReceiptCopy.objects.filter(sale=sale).count(), 2)
        self.assertEqual(copy.copy_no, 2)

    def test_purchase_order_receiving_increases_stock(self):
        po = create_purchase_order(
            branch=self.branch,
            supplier="Metro Wholesale Ltd",
            created_by=self.user,
            items=[{"product": self.product, "ordered_quantity": 5, "unit_cost": Decimal("100.00")}],
        )

        receive_purchase_order(
            purchase_order=po,
            user=self.user,
            items=[{"item": po.items.first(), "received_quantity": 5}],
        )

        self.stock.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(self.stock.quantity, 15)
        self.assertEqual(po.status, "received")

    def test_stocktake_approval_posts_variance(self):
        session = create_stocktake(branch=self.branch, created_by=self.user)
        item = session.items.get(product=self.product)
        item.counted_quantity = 7
        item.save()
        session.status = StocktakeSession.COUNTED
        session.save()

        approve_stocktake(stocktake=session, user=self.user)

        self.stock.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(self.stock.quantity, 7)
        self.assertEqual(session.status, StocktakeSession.APPROVED)

    def test_pin_login_returns_role_permissions(self):
        UserProfile.objects.create(user=self.user, pin=make_password("1234"), role=UserProfile.MANAGER, branch=self.branch)
        client = APIClient()

        response = client.post("/api/pos/auth/login/", {"username": "cashier", "pin": "1234"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profile"]["role"], UserProfile.MANAGER)
        self.assertIn("sale.void", response.data["permissions"])

    def test_custom_permissions_override_role_defaults(self):
        profile = UserProfile.objects.create(
            user=self.user,
            role=UserProfile.ADMIN,
            access_level=UserProfile.BRANCH_STAFF,
            branch=self.branch,
            company=self.branch.company,
            custom_permissions=["dashboard.view"],
            use_custom_permissions=True,
        )

        self.assertEqual(permissions_for_profile(profile), ["dashboard.view"])

        profile.custom_permissions = []
        profile.save(update_fields=["custom_permissions", "updated_at"])

        self.assertEqual(permissions_for_profile(profile), [])

    def test_user_update_persists_manual_rights(self):
        manager = get_user_model().objects.create_user(username="manager", password="pass")
        UserProfile.objects.create(
            user=manager,
            role=UserProfile.ADMIN,
            access_level=UserProfile.COMPANY_ADMIN,
            branch=self.branch,
            company=self.branch.company,
        )
        profile = UserProfile.objects.create(
            user=self.user,
            role=UserProfile.ADMIN,
            access_level=UserProfile.BRANCH_STAFF,
            branch=self.branch,
            company=self.branch.company,
        )
        client = APIClient()
        client.force_authenticate(manager)

        response = client.patch(
            f"/api/pos/users/{profile.id}/",
            {
                "username": "cashier",
                "role": UserProfile.ADMIN,
                "access_level": UserProfile.BRANCH_STAFF,
                "branch": self.branch.id,
                "company": self.branch.company_id,
                "custom_permissions": [],
                "use_custom_permissions": True,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertTrue(profile.use_custom_permissions)
        self.assertEqual(profile.custom_permissions, [])
        self.assertEqual(permissions_for_profile(profile), [])

    def test_shift_filters_ignore_undefined_values(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get("/api/pos/shifts/", {"branch": "undefined", "register": "undefined", "cashier": self.user.id, "status": Shift.OPEN})

        self.assertEqual(response.status_code, 200)

    def test_shift_filters_reject_invalid_ids(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get("/api/pos/shifts/", {"branch": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["branch"], "Expected a numeric id.")

    def test_login_token_scopes_branch_reads_to_profile_branch(self):
        UserProfile.objects.create(
            user=self.user,
            pin=make_password("1234"),
            role=UserProfile.CASHIER,
            access_level=UserProfile.BRANCH_STAFF,
            branch=self.branch,
            company=self.branch.company,
        )
        client = APIClient()

        login_response = client.post("/api/pos/auth/login/", {"username": "cashier", "pin": "1234"}, format="json")
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("token", login_response.data)

        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['token']}")
        response = client.get("/api/pos/categories/")
        rows = response.data["results"] if isinstance(response.data, dict) else response.data

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["branch"] for row in rows], [self.branch.id])

    def test_branch_staff_cannot_read_another_branch_with_branch_param(self):
        other_branch = Branch.objects.create(company=self.branch.company, code="WEST", name="West Branch")
        Category.objects.create(branch=other_branch, name="Wines")
        UserProfile.objects.create(
            user=self.user,
            role=UserProfile.CASHIER,
            access_level=UserProfile.BRANCH_STAFF,
            branch=self.branch,
            company=self.branch.company,
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get("/api/pos/categories/", {"branch": other_branch.id})

        self.assertEqual(response.status_code, 403)

    def test_cross_branch_stock_adjustment_is_rejected(self):
        other_branch = Branch.objects.create(company=self.branch.company, code="WEST", name="West Branch")
        other_category = Category.objects.create(branch=other_branch, name="Soft Drinks")
        other_product = Product.objects.create(
            branch=other_branch,
            category=other_category,
            name="Soda",
            sku="SODA-001",
            retail_price=Decimal("100.00"),
            wholesale_price=Decimal("90.00"),
            tax_rate=Decimal("0.00"),
        )
        UserProfile.objects.create(
            user=self.user,
            role=UserProfile.INVENTORY,
            access_level=UserProfile.BRANCH_STAFF,
            branch=self.branch,
            company=self.branch.company,
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            "/api/pos/stock/adjust/",
            {"branch": self.branch.id, "product": other_product.id, "quantity_delta": 1, "reason": "Test"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("product", response.data)

    def test_company_admin_cannot_list_other_company_branches(self):
        other_company = Company.objects.create(name="Other Company", code="OTHER")
        Branch.objects.create(company=other_company, code="OTHER", name="Other Branch")
        UserProfile.objects.create(
            user=self.user,
            role=UserProfile.ADMIN,
            access_level=UserProfile.COMPANY_ADMIN,
            branch=self.branch,
            company=self.branch.company,
        )
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get("/api/pos/branches/", {"company": other_company.id})
        rows = response.data["results"] if isinstance(response.data, dict) else response.data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rows, [])

    def test_sale_return_restocks_inventory(self):
        sale = checkout_sale(
            cashier=self.user,
            branch=self.branch,
            register=self.register,
            shift=self.shift,
            mode=Sale.RETAIL,
            items=[{"product": self.product, "quantity": 2}],
            payments=[{"method": Payment.CASH, "amount": Decimal("400.00")}],
        )
        sale_return = create_sale_return(
            sale=sale,
            processed_by=self.user,
            reason="Customer return",
            items=[{"product": self.product, "quantity": 1}],
        )
        complete_sale_return(sale_return=sale_return, user=self.user)
        self.stock.refresh_from_db()
        sale_return.refresh_from_db()
        self.assertEqual(sale_return.status, SaleReturn.COMPLETED)
        self.assertEqual(self.stock.quantity, 9)

    def test_sales_control_endpoints(self):
        UserProfile.objects.create(
            user=self.user,
            role=UserProfile.MANAGER,
            access_level=UserProfile.BRANCH_STAFF,
            branch=self.branch,
            company=self.branch.company,
        )
        checkout_sale(
            cashier=self.user,
            branch=self.branch,
            register=self.register,
            shift=self.shift,
            mode=Sale.RETAIL,
            items=[{"product": self.product, "quantity": 1, "discount_amount": Decimal("20.00")}],
            payments=[{"method": Payment.CASH, "amount": Decimal("180.00")}],
        )
        client = APIClient()
        client.force_authenticate(self.user)

        transactions = client.get("/api/pos/sales/transactions/", {"branch": self.branch.id})
        self.assertEqual(transactions.status_code, 200)

        discounts = client.get("/api/pos/sales/discounts/", {"branch": self.branch.id})
        self.assertEqual(discounts.status_code, 200)
        self.assertTrue(len(discounts.data) >= 1)

        reports = client.get("/api/pos/sales/reports/", {"branch": self.branch.id, "type": "daily_summary"})
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(reports.data["report"], "daily_summary")
