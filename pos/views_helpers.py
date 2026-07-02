"""
Shared utilities imported by every views_*.py module.
Keep all helpers here so the domain files stay focused on viewset logic.
"""
import csv
import datetime
import io
from decimal import Decimal

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import AuditLog, Branch, UserProfile
from .permissions import get_pos_profile, profile_company, user_can_access_branch
from .serializers import BranchSerializer, CompanySerializer
from .rbac import (
    ADMIN_SECTION_PERMISSIONS,
    can_access_admin_section,
    permissions_for_profile,
)


# ---------------------------------------------------------------------------
# Integer param helpers
# ---------------------------------------------------------------------------

def _positive_int_value(value, name):
    if value in (None, "", "undefined", "null"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Expected a numeric id."}) from exc
    if parsed <= 0:
        raise ValidationError({name: "Expected a positive numeric id."})
    return parsed


def _positive_int_query_param(query_params, name):
    return _positive_int_value(query_params.get(name), name)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    response = Response(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _pdf_response(filename, title, headers, rows):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph(title, styles["Title"]))
        elements.append(Paragraph(" ", styles["Normal"]))
        data = [headers] + [[str(cell) for cell in row] for row in rows]
        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        response = Response(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except ImportError:
        html = (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title>"
            "<style>body{font-family:Arial,sans-serif;margin:20px}h1{color:#1e293b}"
            "table{border-collapse:collapse;width:100%;margin-top:20px}"
            "th,td{border:1px solid #e2e8f0;padding:8px;text-align:left;font-size:12px}"
            "th{background:#f1f5f9}</style></head><body>"
            f"<h1>{title}</h1><table><thead><tr>"
            + "".join(f"<th>{h}</th>" for h in headers)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
            + "</tbody></table></body></html>"
        )
        response = Response(html, content_type="text/html")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ---------------------------------------------------------------------------
# Role/access checks
# ---------------------------------------------------------------------------

def is_super_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        user.is_superuser
        or (profile and profile.access_level == UserProfile.SUPER_ADMIN)
    )


def is_company_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        is_super_admin(user)
        or (profile and profile.access_level in [UserProfile.COMPANY_ADMIN, UserProfile.SUPER_ADMIN])
    )


def is_branch_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        is_company_admin(user)
        or (profile and profile.access_level in [
            UserProfile.BRANCH_ADMIN, UserProfile.COMPANY_ADMIN, UserProfile.SUPER_ADMIN
        ])
    )


# ---------------------------------------------------------------------------
# Branch resolution
# ---------------------------------------------------------------------------

def _active_branch(user):
    profile = get_pos_profile(user)
    return profile.branch if (profile and profile.branch_id) else None


def _active_company(user):
    return profile_company(get_pos_profile(user))


def _branch_filter_kwargs(branch_field, branch):
    if branch_field == "id":
        return {"id": branch.id}
    return {f"{branch_field}_id": branch.id}


def _get_active_branch_by_id(branch_id):
    branch = Branch.objects.select_related("company").filter(pk=branch_id, is_active=True).first()
    if not branch:
        raise ValidationError({"branch": "Branch not found or inactive."})
    return branch


def _resolve_read_branch(request):
    branch_id = _positive_int_query_param(request.query_params, "branch")
    if branch_id is not None:
        branch = _get_active_branch_by_id(branch_id)
        if not user_can_access_branch(request.user, branch):
            raise PermissionDenied("You do not have access to this branch.")
        return branch
    branch = _active_branch(request.user)
    if branch and user_can_access_branch(request.user, branch):
        return branch
    return None


def _resolve_write_branch(request):
    branch_id = _positive_int_value(
        request.data.get("branch") or request.query_params.get("branch"),
        "branch",
    )
    branch = _get_active_branch_by_id(branch_id) if branch_id is not None else _active_branch(request.user)
    if not branch:
        profile = get_pos_profile(request.user)
        company = profile.company if profile else None
        if company:
            company_branches = Branch.objects.filter(company=company, is_active=True)
            if company_branches.count() == 1:
                branch = company_branches.first()
    if not branch:
        raise ValidationError({"branch": "Active branch is required."})
    if not user_can_access_branch(request.user, branch):
        raise PermissionDenied("You do not have access to this branch.")
    return branch


def _filter_branch_scoped_queryset(queryset, request, branch_field="branch"):
    branch = _resolve_read_branch(request)
    if not branch:
        return queryset.none()
    return queryset.filter(**_branch_filter_kwargs(branch_field, branch))


def _is_cashier_only(user):
    """
    True when the user is a plain cashier or voiding-only role with no management access.
    These users should only see their own shifts and transactions, not their colleagues'.
    """
    try:
        profile = user.pos_profile
        return (
            profile.role == UserProfile.CASHIER
            and profile.access_level == UserProfile.BRANCH_STAFF
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Audit + change tracking
# ---------------------------------------------------------------------------

def _audit(request, action, entity, entity_id, branch=None, notes=""):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id),
        branch=branch,
        notes=notes,
    )


def _changed_fields(instance, serializer, fields):
    changes = []
    for field in fields:
        if field not in serializer.validated_data:
            continue
        old_value = getattr(instance, field, None)
        new_value = serializer.validated_data[field]
        if old_value != new_value:
            changes.append(f"{field}: {old_value} -> {new_value}")
    return "; ".join(changes)


# ---------------------------------------------------------------------------
# Auth context payloads
# ---------------------------------------------------------------------------

def _build_context_payload(profile):
    branch = profile.branch
    company = profile.company or (branch.company if branch else None)

    if profile.access_level == UserProfile.SUPER_ADMIN:
        sibling_branches = Branch.objects.filter(is_active=True)
    elif profile.access_level == UserProfile.COMPANY_ADMIN:
        sibling_branches = (
            Branch.objects.filter(company=company, is_active=True)
            if company else Branch.objects.none()
        )
    else:
        sibling_branches = (
            Branch.objects.filter(id=branch.id, is_active=True)
            if branch else Branch.objects.none()
        )

    return {
        "company": CompanySerializer(company).data if company else None,
        "branch": BranchSerializer(branch).data if branch else None,
        "company_branches": BranchSerializer(sibling_branches, many=True).data,
        "access_level": profile.access_level,
    }


def _auth_permissions_payload(profile, user):
    permissions = permissions_for_profile(profile)
    if user.is_superuser or (profile.role == UserProfile.ADMIN and not profile.use_custom_permissions):
        permissions = ["*"]
    admin_sections = {
        name: can_access_admin_section(permissions, name)
        for name in ADMIN_SECTION_PERMISSIONS
    }
    return {"permissions": permissions, "admin_sections": admin_sections}
