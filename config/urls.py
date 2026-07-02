import os
from pathlib import Path

from django.contrib import admin
from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from django.views import View


class SPACatchAllView(View):
    """Serve index.html for any non-API route (SPA client-side routing)."""
    def get(self, request, *args, **kwargs):
        index_path = Path(settings.FRONTEND_DIST_DIR) / "index.html"
        if index_path.exists():
            return FileResponse(open(index_path, "rb"), content_type="text/html")
        raise Http404("Frontend not built. Run: npm run build")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/pos/", include("pos.urls")),
    path("api/inventory/", include("inventory.urls")),
]

# In desktop mode serve the SPA — must be last (catch-all).
# WhiteNoise middleware handles /assets/, /favicon.ico, etc. before this runs.
# We also exclude those prefixes here so a misconfiguration never serves index.html
# with the wrong MIME type (which breaks strict MIME checking in browsers/Electron).
if getattr(settings, "DESKTOP_MODE", False):
    urlpatterns += [
        re_path(r"^(?!api/|admin/|static/|assets/).*$", SPACatchAllView.as_view(), name="spa-index"),
    ]
