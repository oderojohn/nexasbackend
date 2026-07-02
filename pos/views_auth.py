"""Authentication and user-profile viewsets."""
import logging
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.hashers import check_password
from django.conf import settings
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .authentication import make_pos_token, make_token_hash
from .models import AuditLog, BlacklistedToken, Branch, Company, UserProfile
from .permissions import get_pos_profile
from .rbac import role_permission_matrix
from .serializers import (
    LoginSerializer,
    SwitchBranchSerializer,
    UserProfileSerializer,
)
from .views_helpers import (
    _active_branch,
    _active_company,
    _auth_permissions_payload,
    _build_context_payload,
    _get_active_branch_by_id,
    _positive_int_query_param,
    is_branch_admin,
    is_company_admin,
    is_super_admin,
)

logger = logging.getLogger(__name__)


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class AuthViewSet(viewsets.ViewSet):
    def get_permissions(self):
        if self.action in ("login", "ping"):
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_throttles(self):
        if self.action == "login":
            return [LoginRateThrottle()]
        return super().get_throttles()

    @action(detail=False, methods=["get", "head"])
    def ping(self, request):
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        password = serializer.validated_data.get("password", "")
        pin = serializer.validated_data.get("pin", "")
        company_code = serializer.validated_data.get("company_code", "").strip()

        company = None
        if company_code:
            company = Company.objects.filter(code__iexact=company_code, is_active=True).first()
            if not company:
                return Response(
                    {"detail": "Invalid company code."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        user = None

        # Per-company username lookup: try pos_username + company first
        if company:
            profile_by_pos = (
                UserProfile.objects
                .select_related("user")
                .filter(company_id=company.id, pos_username=username, is_active=True)
                .first()
            )
            if profile_by_pos:
                candidate = profile_by_pos.user
                if password and candidate.check_password(password):
                    user = candidate
                elif pin and profile_by_pos.pin and check_password(pin, profile_by_pos.pin):
                    user = candidate

        # Fall back to standard Django username authentication
        if user is None and password:
            user = authenticate(request, username=username, password=password)
        if user is None and pin:
            profile = (
                UserProfile.objects
                .select_related("user")
                .filter(user__username=username, is_active=True)
                .first()
            )
            if profile and profile.pin and check_password(pin, profile.pin):
                user = profile.user

        if user is None or not user.is_active:
            return Response(
                {"detail": "Invalid username, password, or PIN."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={"role": UserProfile.ADMIN if user.is_superuser else UserProfile.CASHIER},
        )
        if not profile.is_active:
            return Response(
                {"detail": "POS profile is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        auth_perms = _auth_permissions_payload(profile, user)
        return Response({
            "user": {
                "id": user.id,
                "username": profile.pos_username or user.username,
                "full_name": user.get_full_name(),
                "is_superuser": user.is_superuser,
            },
            "profile": UserProfileSerializer(profile).data,
            "permissions": auth_perms["permissions"],
            "admin_sections": auth_perms["admin_sections"],
            "token": make_pos_token(user),
            **_build_context_payload(profile),
        })

    @action(detail=False, methods=["post"])
    def logout(self, request):
        token = request.auth
        if token and isinstance(token, str):
            max_age = getattr(settings, "POS_AUTH_TOKEN_MAX_AGE", 3600)
            expires_at = timezone.now() + timedelta(seconds=max_age)
            BlacklistedToken.objects.get_or_create(
                token_hash=make_token_hash(token),
                defaults={"user": request.user, "expires_at": expires_at},
            )
        return Response({"detail": "Logged out successfully."})

    @action(detail=False, methods=["get"])
    def me(self, request):
        profile = get_pos_profile(request.user)
        if not request.user.is_active or not profile or not profile.is_active:
            return Response(
                {"detail": "Your POS account is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )
        auth_perms = _auth_permissions_payload(profile, request.user)
        return Response({
            "user": {
                "id": request.user.id,
                "username": profile.pos_username or request.user.username,
                "full_name": request.user.get_full_name(),
                "is_superuser": request.user.is_superuser,
            },
            "profile": UserProfileSerializer(profile).data,
            "permissions": auth_perms["permissions"],
            "admin_sections": auth_perms["admin_sections"],
            **_build_context_payload(profile),
        })

    @action(detail=False, methods=["post"], url_path="switch-branch")
    def switch_branch(self, request):
        if not is_company_admin(request.user):
            return Response(
                {"detail": "Only company admins or super admins can switch branch."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SwitchBranchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile = get_pos_profile(request.user)
        if not profile:
            return Response(
                {"detail": "No POS profile found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_branch_id = serializer.validated_data["branch"]
        branch_qs = Branch.objects.select_related("company").filter(pk=new_branch_id, is_active=True)

        if profile.access_level == UserProfile.SUPER_ADMIN:
            pass
        elif profile.access_level == UserProfile.COMPANY_ADMIN:
            branch_qs = branch_qs.filter(company=profile.company)
        else:
            return Response(
                {"detail": "You do not have permission to switch branches."},
                status=status.HTTP_403_FORBIDDEN,
            )

        branch = branch_qs.first()
        if not branch:
            return Response(
                {"detail": "Branch not found, inactive, or outside your access scope."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_branch = profile.branch
        profile.branch = branch
        profile.company = branch.company
        profile.save(update_fields=["branch", "company", "updated_at"])

        AuditLog.objects.create(
            user=request.user,
            action="admin.switch_branch",
            entity="UserProfile",
            entity_id=str(profile.id),
            branch=branch,
            notes=f"Switched from branch={old_branch.id if old_branch else None} to branch={branch.id}",
        )

        return Response({
            "profile": UserProfileSerializer(profile).data,
            "reload": True,
            **_auth_permissions_payload(profile, request.user),
            **_build_context_payload(profile),
        })

    @action(detail=False, methods=["post"], url_path="switch-company")
    def switch_company(self, request):
        if not is_super_admin(request.user):
            return Response(
                {"detail": "Only super admins can switch company."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company_id = request.data.get("company")
        if not company_id:
            return Response(
                {"detail": "company_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = get_pos_profile(request.user)
        if not profile:
            return Response(
                {"detail": "No POS profile found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company = Company.objects.filter(pk=company_id, is_active=True).first()
        if not company:
            return Response(
                {"detail": "Company not found or inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        branch = Branch.objects.filter(company=company, is_active=True).first()
        if not branch:
            return Response(
                {"detail": "No active branches in this company."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_company = profile.company
        profile.company = company
        profile.branch = branch
        profile.save(update_fields=["company", "branch", "updated_at"])

        AuditLog.objects.create(
            user=request.user,
            action="admin.switch_company",
            entity="UserProfile",
            entity_id=str(profile.id),
            branch=branch,
            notes=f"Switched from company={old_company.id if old_company else None} to company={company.id}",
        )

        return Response({
            "profile": UserProfileSerializer(profile).data,
            "reload": True,
            **_auth_permissions_payload(profile, request.user),
            **_build_context_payload(profile),
        })


class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.select_related("user", "branch__company").order_by("id")
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        branch_param = _positive_int_query_param(self.request.query_params, "branch")

        if is_super_admin(user):
            return queryset.filter(branch_id=branch_param) if branch_param is not None else queryset

        from django.db.models import Q
        company = _active_company(user)
        if is_company_admin(user) and company:
            queryset = queryset.filter(Q(company=company) | Q(branch__company=company))
            if branch_param is not None:
                branch = _get_active_branch_by_id(branch_param)
                if branch.company_id != company.id:
                    return queryset.none()
                queryset = queryset.filter(branch=branch)
            return queryset

        branch = _active_branch(user)
        if branch_param is not None and (not branch or branch_param != branch.id):
            return queryset.none()
        return queryset.filter(branch=branch) if branch else queryset.none()

    def _ensure_can_manage_users(self):
        if not is_branch_admin(self.request.user):
            raise PermissionDenied("Only branch admins, company admins, or super admins can manage POS users.")

    def _ensure_profile_scope(self, profile):
        actor = self.request.user
        if is_super_admin(actor):
            return
        if profile.access_level == UserProfile.SUPER_ADMIN:
            raise PermissionDenied("Only super admins can grant super-admin access.")
        actor_company = _active_company(actor)
        if is_company_admin(actor):
            profile_company_id = profile.company_id or (profile.branch.company_id if profile.branch_id else None)
            if not actor_company or profile_company_id != actor_company.id:
                raise PermissionDenied("You can only manage users in your company.")
            return
        actor_branch = _active_branch(actor)
        if (
            profile.access_level in [UserProfile.COMPANY_ADMIN, UserProfile.SUPER_ADMIN]
            or not actor_branch
            or profile.branch_id != actor_branch.id
        ):
            raise PermissionDenied("Branch admins can only manage staff in their branch.")

    def _ensure_profile_scope_data(self, serializer):
        actor = self.request.user
        if is_super_admin(actor):
            return
        access_level = serializer.validated_data.get(
            "access_level",
            getattr(serializer.instance, "access_level", UserProfile.BRANCH_STAFF),
        )
        branch = serializer.validated_data.get("branch") or getattr(serializer.instance, "branch", None)
        company = serializer.validated_data.get("company") or getattr(serializer.instance, "company", None)
        custom_permissions = serializer.validated_data.get("custom_permissions", None)

        if access_level == UserProfile.SUPER_ADMIN:
            raise PermissionDenied("Only super admins can grant super-admin access.")
        if custom_permissions and ("admin.super" in custom_permissions or "admin.company" in custom_permissions):
            raise PermissionDenied("Only super admins can grant system-wide administration permissions.")

        if is_company_admin(actor):
            actor_company = _active_company(actor)
            target_company = company or (branch.company if branch else None)
            if not actor_company or not target_company or target_company.id != actor_company.id:
                raise PermissionDenied("You can only manage users in your company.")
            return

        actor_branch = _active_branch(actor)
        if (
            access_level in [UserProfile.COMPANY_ADMIN, UserProfile.SUPER_ADMIN]
            or not actor_branch
            or not branch
            or branch.id != actor_branch.id
        ):
            raise PermissionDenied("Branch admins can only manage staff in their branch.")

    def perform_create(self, serializer):
        self._ensure_can_manage_users()
        self._ensure_profile_scope_data(serializer)
        profile = serializer.save()
        self._ensure_profile_scope(profile)
        AuditLog.objects.create(
            user=self.request.user,
            action="admin.user.create",
            entity="UserProfile",
            entity_id=str(profile.id),
            branch=profile.branch,
            notes=f"Created POS user {profile.user.username}",
        )

    def perform_update(self, serializer):
        self._ensure_can_manage_users()
        self._ensure_profile_scope_data(serializer)
        profile = serializer.save()
        self._ensure_profile_scope(profile)
        AuditLog.objects.create(
            user=self.request.user,
            action="admin.user.update",
            entity="UserProfile",
            entity_id=str(profile.id),
            branch=profile.branch,
            notes=f"Updated POS user {profile.user.username}",
        )

    def perform_destroy(self, instance):
        self._ensure_can_manage_users()
        self._ensure_profile_scope(instance)
        username = instance.user.username
        branch = instance.branch
        user = instance.user
        profile_id = str(instance.id)
        try:
            instance.delete()
            user.delete()
        except ProtectedError:
            # User has linked records (sales, shifts, etc.) — deactivate instead
            user.is_active = False
            user.save(update_fields=["is_active"])
            AuditLog.objects.create(
                user=self.request.user,
                action="admin.user.deactivate",
                entity="UserProfile",
                entity_id=profile_id,
                branch=branch,
                notes=f"Deactivated POS user {username} (has linked records, cannot delete)",
            )
            return
        AuditLog.objects.create(
            user=self.request.user,
            action="admin.user.delete",
            entity="UserProfile",
            entity_id=profile_id,
            branch=branch,
            notes=f"Deleted POS user {username}",
        )

    @action(detail=False, methods=["get"], url_path="role-options")
    def role_options(self, request):
        matrix = role_permission_matrix()
        return Response({
            "roles": matrix["roles"],
            "access_levels": [
                {"value": value, "label": label}
                for value, label in UserProfile.ACCESS_LEVEL_CHOICES
            ],
            "permissions": {row["role"]: row["permissions"] for row in matrix["matrix"]},
            "permission_catalog": matrix["catalog"],
            "role_matrix": matrix["matrix"],
        })
