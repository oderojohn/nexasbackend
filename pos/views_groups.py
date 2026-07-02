"""Permission group CRUD viewset."""
from rest_framework import viewsets

from .models import PermissionGroup
from .serializers import PermissionGroupSerializer
from .views_helpers import _active_company


class PermissionGroupViewSet(viewsets.ModelViewSet):
    serializer_class = PermissionGroupSerializer
    queryset = PermissionGroup.objects.select_related('company').prefetch_related('members')

    def get_queryset(self):
        qs = super().get_queryset()
        company_id = self.request.query_params.get('company')
        if company_id:
            qs = qs.filter(company_id=company_id)
            return qs
        company = _active_company(self.request.user)
        if company:
            return qs.filter(company=company)
        if self.request.user.is_superuser:
            return qs
        return qs.none()
