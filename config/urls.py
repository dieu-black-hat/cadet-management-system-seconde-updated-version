from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("cadets/", include("cadets.urls")),
    path("statements/", include("discipline.urls")),
    path("medical/", include("medical.urls")),
    path("reports/", include("reports.urls")),
    path("notifications/", include("notifications.urls")),
    path("audit/", include("audit.urls")),
]

# The Django admin is disabled by default: all administration goes through the
# permission-checked application screens. Enable only for break-glass use.
if settings.DEBUG and getattr(settings, "ENABLE_DJANGO_ADMIN", False):
    urlpatterns.append(path("django-admin/", admin.site.urls))

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
