"""Company, Branch, Register, Category and Product viewsets."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import (
    AuditLog,
    Branch,
    Category,
    Company,
    InventoryStock,
    Product,
    Register,
    StockMovement,
)
from .serializers import (
    BranchSerializer,
    CategorySerializer,
    CompanySerializer,
    ProductSerializer,
    RegisterSerializer,
)
from .services import ensure_default_register
from .views_helpers import (
    _active_company,
    _audit,
    _changed_fields,
    _filter_branch_scoped_queryset,
    _get_active_branch_by_id,
    _positive_int_query_param,
    _resolve_read_branch,
    _resolve_write_branch,
    is_company_admin,
    is_super_admin,
)


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.filter(is_active=True)
    serializer_class = CompanySerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset
        company_id = _positive_int_query_param(self.request.query_params, "company")

        if is_super_admin(user):
            return queryset.filter(id=company_id) if company_id is not None else queryset

        company = _active_company(user)
        if company:
            if company_id is not None and company_id != company.id:
                return queryset.none()
            return queryset.filter(id=company.id)
        return queryset.none()

    def perform_create(self, serializer):
        if not is_super_admin(self.request.user):
            raise PermissionDenied("Only super admins can create companies.")
        company = serializer.save()
        from pos.management.commands.create_default_groups import seed_default_groups_for_company
        seed_default_groups_for_company(company)
        _audit(self.request, "admin.company.create", "Company", company.id, notes=f"Created company {company.name}")

    def perform_update(self, serializer):
        if not is_super_admin(self.request.user):
            raise PermissionDenied("Only super admins can update companies.")
        changes = _changed_fields(serializer.instance, serializer, ["name", "currency", "vat_rate", "is_active"])
        company = serializer.save()
        _audit(self.request, "admin.company.update", "Company", company.id, notes=changes or f"Updated company {company.name}")

    def perform_destroy(self, instance):
        if not is_super_admin(self.request.user):
            raise PermissionDenied("Only super admins can delete companies.")
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        _audit(self.request, "admin.company.delete", "Company", instance.id, notes=f"Deactivated company {instance.name}")


class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.select_related("company").filter(is_active=True)
    serializer_class = BranchSerializer

    def get_queryset(self):
        user = self.request.user
        company_id = _positive_int_query_param(self.request.query_params, "company")
        queryset = self.queryset

        if is_super_admin(user):
            return queryset.filter(company_id=company_id) if company_id is not None else queryset

        company = _active_company(user)
        if is_company_admin(user) and company:
            if company_id is not None and company_id != company.id:
                return queryset.none()
            return queryset.filter(company_id=company.id)

        from .views_helpers import _active_branch
        branch = _active_branch(user)
        if not branch:
            return queryset.none()
        return queryset.filter(id=branch.id)

    def perform_create(self, serializer):
        company = serializer.validated_data.get("company")
        if not is_super_admin(self.request.user):
            if not is_company_admin(self.request.user):
                raise PermissionDenied("Only company admins can create branches.")
            active_company = _active_company(self.request.user)
            if not active_company or company.id != active_company.id:
                raise PermissionDenied("You can only create branches in your company.")
        branch = serializer.save()
        ensure_default_register(branch)
        _audit(self.request, "admin.branch.create", "Branch", branch.id, branch=branch, notes=f"Created branch {branch.code}")

    def perform_update(self, serializer):
        company = serializer.validated_data.get("company", serializer.instance.company)
        if not is_super_admin(self.request.user):
            if not is_company_admin(self.request.user):
                raise PermissionDenied("Only company admins can update branches.")
            active_company = _active_company(self.request.user)
            if not active_company or company.id != active_company.id:
                raise PermissionDenied("You can only update branches in your company.")
        changes = _changed_fields(serializer.instance, serializer, ["code", "name", "location", "company", "is_active"])
        branch = serializer.save()
        _audit(self.request, "admin.branch.update", "Branch", branch.id, branch=branch, notes=changes or f"Updated branch {branch.code}")

    def perform_destroy(self, instance):
        if not is_super_admin(self.request.user):
            if not is_company_admin(self.request.user):
                raise PermissionDenied("Only company admins can delete branches.")
            active_company = _active_company(self.request.user)
            if not active_company or instance.company_id != active_company.id:
                raise PermissionDenied("You can only delete branches in your company.")
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        _audit(self.request, "admin.branch.delete", "Branch", instance.id, branch=instance, notes=f"Deactivated branch {instance.code}")


class RegisterViewSet(viewsets.ModelViewSet):
    queryset = Register.objects.select_related("branch__company")
    serializer_class = RegisterSerializer

    def get_queryset(self):
        return _filter_branch_scoped_queryset(super().get_queryset(), self.request)

    @action(detail=False, methods=["post"], url_path="ensure-default")
    def ensure_default(self, request):
        branch = _resolve_write_branch(request)
        register = ensure_default_register(branch)
        return Response(RegisterSerializer(register).data, status=status.HTTP_200_OK)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.filter(is_active=True).select_related("branch__company")
    serializer_class = CategorySerializer

    def get_queryset(self):
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def perform_create(self, serializer):
        category = serializer.save(branch=_resolve_write_branch(self.request))
        _audit(self.request, "inventory.category.create", "Category", category.id, branch=category.branch, notes=f"Created category {category.name}")

    def perform_update(self, serializer):
        changes = _changed_fields(serializer.instance, serializer, ["name", "color", "is_active"])
        category = serializer.save()
        _audit(self.request, "inventory.category.update", "Category", category.id, branch=category.branch, notes=changes or f"Updated category {category.name}")

    def perform_destroy(self, instance):
        if instance.products.filter(is_active=True).exists():
            raise ValidationError({"category": "Deactivate or move products before deleting this category."})
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        _audit(self.request, "inventory.category.delete", "Category", instance.id, branch=instance.branch, notes=f"Deactivated category {instance.name}")


class ProductViewSet(viewsets.ModelViewSet):
    queryset = (
        Product.objects
        .filter(is_active=True)
        .select_related("branch__company", "category")
        .prefetch_related("stock_rows")
    )
    serializer_class = ProductSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        branch = (
            _resolve_write_branch(self.request)
            if self.action in {"create", "update", "partial_update"}
            else _resolve_read_branch(self.request)
        )
        context["branch_id"] = branch.id if branch else None
        return context

    def get_queryset(self):
        from django.db.models import Q
        queryset = _filter_branch_scoped_queryset(super().get_queryset(), self.request)
        search = self.request.query_params.get("search")
        category = self.request.query_params.get("category")
        barcode = self.request.query_params.get("barcode")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(sku__icontains=search) | Q(barcode__icontains=search)
            )
        if category:
            queryset = queryset.filter(category_id=category)
        if barcode:
            queryset = queryset.filter(barcode=barcode)
        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        branch = _resolve_write_branch(request)
        initial_stock = int(request.data.get("initial_stock") or 0)
        user_id = request.data.get("user")

        if initial_stock < 0:
            return Response(
                {"initial_stock": "Opening stock cannot be negative."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save(branch=branch)
        _audit(request, "inventory.product.create", "Product", product.id, branch=branch, notes=f"Created product {product.sku}")

        if initial_stock:
            user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
            stock, _ = InventoryStock.objects.select_for_update().get_or_create(
                branch=branch, product=product, defaults={"quantity": 0},
            )
            stock.quantity += initial_stock
            stock.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                branch=branch, product=product, quantity_delta=initial_stock,
                reason=StockMovement.ADJUSTMENT, reference="Opening stock", user=user,
            )
            AuditLog.objects.create(
                user=user, action="product.create_with_opening_stock",
                entity="Product", entity_id=str(product.id), branch=branch,
                notes=f"Opening stock: {initial_stock}",
            )

        headers = self.get_success_headers(serializer.data)
        return Response(self.get_serializer(product).data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        fields = [
            "name", "sku", "barcode", "category", "retail_price", "wholesale_price",
            "cost_price", "tax_rate", "reorder_point", "is_active",
        ]
        changes = _changed_fields(serializer.instance, serializer, fields)
        product = serializer.save()
        _audit(self.request, "inventory.product.update", "Product", product.id, branch=product.branch, notes=changes or f"Updated product {product.sku}")

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        _audit(self.request, "inventory.product.delete", "Product", instance.id, branch=instance.branch, notes=f"Deactivated product {instance.sku}")
