from django.core.mail import get_connection, EmailMultiAlternatives
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Company, CompanySettings, default_company_settings
from .permissions import get_pos_profile, profile_company
from .rbac import (
    ADMIN_SECTION_PERMISSIONS,
    PERMISSION_CATALOG,
    can_access_admin_section,
    has_permission,
    permissions_for_profile,
    role_permission_matrix,
)
from .serializers import CompanySettingsSerializer
from .views import _positive_int_query_param, is_company_admin, is_super_admin


def _resolve_settings_company(request):
    company_id = _positive_int_query_param(request.query_params, "company")
    if company_id is not None:
        company = Company.objects.filter(pk=company_id, is_active=True).first()
        if not company:
            raise ValidationError({"company": "Company not found."})
    else:
        profile = get_pos_profile(request.user)
        company = profile.company if profile else None
        if not company and profile and profile.branch_id:
            company = profile.branch.company
    if not company:
        raise ValidationError({"company": "Company context is required."})
    if not is_super_admin(request.user):
        user_company = profile_company(get_pos_profile(request.user))
        if not user_company or company.id != user_company.id:
            raise PermissionDenied("You do not have access to this company's settings.")
    return company


def get_or_create_company_settings(company):
    settings, created = CompanySettings.objects.get_or_create(
        company=company,
        defaults=default_company_settings(),
    )
    return settings


def _mask_email_config(data):
    """Replace the stored SMTP password with *** in API responses."""
    if isinstance(data, dict) and "email_config" in data:
        cfg = dict(data.get("email_config") or {})
        if cfg.get("password"):
            cfg["password"] = "***"
        data = {**data, "email_config": cfg}
    return data


def _mask_cloud_config(data):
    """Replace the cloud sync token with *** in API responses."""
    if isinstance(data, dict) and "cloud_config" in data:
        cfg = dict(data.get("cloud_config") or {})
        if cfg.get("cloud_sync_token"):
            cfg["cloud_sync_token"] = "***"
        data = {**data, "cloud_config": cfg}
    return data


def _mask_credentials(data):
    return _mask_cloud_config(_mask_email_config(data))


def _resolve_email_cfg(settings_obj):
    defaults = default_company_settings().get("email_config", {})
    return {**defaults, **(settings_obj.email_config or {})}


def _send_test_email(cfg, recipient):
    host = cfg.get("host", "")
    if not host:
        raise ValueError("SMTP host is not configured.")
    port = int(cfg.get("port", 587))
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    use_tls = bool(cfg.get("use_tls", True))
    from_name = cfg.get("from_name", "Nexa POS")
    from_email = cfg.get("from_email", "") or username
    from_header = f"{from_name} <{from_email}>" if from_name else from_email

    connection = get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=host,
        port=port,
        username=username,
        password=password,
        use_tls=use_tls,
        fail_silently=False,
    )
    msg = EmailMultiAlternatives(
        subject="Nexa POS — Test Email",
        body="This is a test email from Nexa POS. Your email configuration is working correctly.",
        from_email=from_header,
        to=[recipient],
        connection=connection,
    )
    msg.attach_alternative(
        """<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px">
           <div style="background:linear-gradient(135deg,#059669,#047857);border-radius:12px;padding:24px;color:#fff;text-align:center">
             <h1 style="margin:0;font-size:20px;font-weight:800">Nexa POS</h1>
             <p style="margin:8px 0 0;font-size:13px;opacity:.85">Email configuration test</p>
           </div>
           <div style="padding:24px 0;text-align:center">
             <p style="font-size:15px;color:#1e293b">Your SMTP settings are working correctly.</p>
             <p style="font-size:13px;color:#64748b">Scheduled reports will be delivered to this account.</p>
           </div>
        </div>""",
        "text/html",
    )
    msg.send(fail_silently=False)


class CompanySettingsViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _ensure_can_edit(self, request):
        perms = permissions_for_profile(get_pos_profile(request.user))
        if not has_permission(perms, "admin.settings") and not has_permission(perms, "*"):
            raise PermissionDenied("You do not have permission to change settings.")

    def list(self, request):
        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)
        return Response(_mask_credentials(CompanySettingsSerializer(settings_obj).data))

    def partial_update(self, request, pk=None):
        self._ensure_can_edit(request)
        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)
        serializer = CompanySettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(_mask_credentials(CompanySettingsSerializer(settings_obj).data))

    @action(detail=False, methods=["get"], url_path="by-company")
    def by_company(self, request):
        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)
        return Response(_mask_credentials(CompanySettingsSerializer(settings_obj).data))

    @action(detail=False, methods=["patch"], url_path="update-section")
    def update_section(self, request):
        self._ensure_can_edit(request)
        section = request.data.get("section")
        values = request.data.get("values")
        if not section or values is None:
            raise ValidationError({"detail": "section and values are required."})
        allowed = set(default_company_settings().keys())
        if section not in allowed:
            raise ValidationError({"section": f"Expected one of: {', '.join(sorted(allowed))}"})
        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)
        current = getattr(settings_obj, section) or {}
        if not isinstance(values, dict):
            raise ValidationError({"values": "Must be an object."})
        # Password masking: keep stored secret if frontend sends the *** placeholder
        if section == "email_config":
            incoming_pw = values.get("password")
            if incoming_pw in ("***", None, "") and "password" in values and current.get("password"):
                values = {**values, "password": current["password"]}
        if section == "cloud_config":
            incoming_token = values.get("cloud_sync_token")
            if incoming_token in ("***", None, "") and "cloud_sync_token" in values and current.get("cloud_sync_token"):
                values = {**values, "cloud_sync_token": current["cloud_sync_token"]}
        merged = {**current, **values}
        setattr(settings_obj, section, merged)
        settings_obj.save(update_fields=[section, "updated_at"])
        return Response(_mask_credentials(CompanySettingsSerializer(settings_obj).data))

    @action(detail=False, methods=["post"], url_path="test-email")
    def test_email(self, request):
        self._ensure_can_edit(request)
        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)
        cfg = _resolve_email_cfg(settings_obj)
        recipient = (request.data.get("recipient") or "").strip()
        if not recipient:
            raise ValidationError({"recipient": "A recipient email address is required."})
        try:
            _send_test_email(cfg, recipient)
            return Response({"detail": f"Test email sent to {recipient}."})
        except Exception as exc:
            return Response({"detail": f"Failed to send: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="cloud-connect")
    def cloud_connect(self, request):
        """Authenticate against the cloud backend and store the token locally."""
        import json
        import time
        from urllib.request import Request, urlopen
        from urllib.error import URLError, HTTPError

        self._ensure_can_edit(request)
        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)

        cloud_url = (request.data.get("cloud_api_url") or "").rstrip("/")
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        branch_id = (request.data.get("branch_id") or "").strip()

        if not cloud_url:
            raise ValidationError({"cloud_api_url": "Cloud API URL is required."})
        if not username or not password:
            raise ValidationError({"detail": "Cloud admin username and password are required."})

        # Step 1: fetch cloud company list (public) for pos_username resolution
        companies_url = f"{cloud_url}/api/pos/auth/companies/"
        cloud_company_id = None
        try:
            with urlopen(Request(companies_url, method="GET"), timeout=10) as resp:
                companies = json.loads(resp.read().decode())
            if companies:
                cloud_company_id = companies[0]["id"]
        except Exception:
            pass  # fall back to Django auth

        # Step 2: login with company context so pos_username is resolved
        login_url = f"{cloud_url}/api/pos/auth/login/"
        login_payload = {"username": username, "password": password}
        if cloud_company_id is not None:
            login_payload["company"] = cloud_company_id
        req = Request(login_url, data=json.dumps(login_payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")

        t0 = time.monotonic()
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except HTTPError as exc:
            body = exc.read().decode() if hasattr(exc, "read") else ""
            try:
                detail = json.loads(body).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            return Response({"detail": f"Cloud rejected login: {detail}"}, status=status.HTTP_401_UNAUTHORIZED)
        except URLError as exc:
            return Response({"detail": f"Could not reach cloud: {exc.reason}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": f"Connection error: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        token = data.get("token", "")
        if not token:
            return Response({"detail": "Cloud login succeeded but returned no token."}, status=status.HTTP_400_BAD_REQUEST)

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Persist credentials — never store the admin password
        current = settings_obj.cloud_config or {}
        settings_obj.cloud_config = {
            **current,
            "cloud_api_url": cloud_url,
            "cloud_sync_token": token,
            "branch_id": branch_id,
        }
        settings_obj.save(update_fields=["cloud_config", "updated_at"])

        return Response({
            "connected": True,
            "cloud_company": data.get("company", {}).get("name", ""),
            "cloud_user": data.get("user", {}).get("username", username),
            "latency_ms": latency_ms,
        })

    @action(detail=False, methods=["post"], url_path="cloud-test")
    def cloud_test(self, request):
        """Ping the cloud backend with the stored token to verify the connection."""
        import json
        import time
        from urllib.request import Request, urlopen
        from urllib.error import URLError

        company = _resolve_settings_company(request)
        settings_obj = get_or_create_company_settings(company)
        cfg = settings_obj.cloud_config or {}

        cloud_url = cfg.get("cloud_api_url", "").rstrip("/")
        token = cfg.get("cloud_sync_token", "")

        if not cloud_url or not token:
            return Response({"connected": False, "detail": "Cloud sync is not configured. Use Connect first."})

        ping_url = f"{cloud_url}/api/pos/auth/ping/"
        req = Request(ping_url, method="GET")
        req.add_header("Authorization", f"Bearer {token}")

        t0 = time.monotonic()
        try:
            with urlopen(req, timeout=10) as resp:
                json.loads(resp.read().decode())
            latency_ms = int((time.monotonic() - t0) * 1000)
            return Response({"connected": True, "latency_ms": latency_ms, "cloud_url": cloud_url})
        except URLError as exc:
            return Response({"connected": False, "detail": str(exc.reason)})
        except Exception as exc:
            return Response({"connected": False, "detail": str(exc)})


class AdminRbacViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="catalog")
    def catalog(self, request):
        profile = get_pos_profile(request.user)
        effective = permissions_for_profile(profile)
        return Response({
            "permissions": effective,
            "catalog": [
                {"code": code, **meta}
                for code, meta in PERMISSION_CATALOG.items()
            ],
            "admin_sections": ADMIN_SECTION_PERMISSIONS,
            "role_matrix": role_permission_matrix(),
        })

    @action(detail=False, methods=["get"], url_path="my-access")
    def my_access(self, request):
        profile = get_pos_profile(request.user)
        perms = permissions_for_profile(profile)
        sections = {
            name: can_access_admin_section(perms, name)
            for name in ADMIN_SECTION_PERMISSIONS
        }
        return Response({
            "role": profile.role if profile else None,
            "access_level": profile.access_level if profile else None,
            "permissions": perms,
            "admin_sections": sections,
        })
