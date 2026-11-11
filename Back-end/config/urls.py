from django.contrib import admin
from django.urls import include, path

from apps.rooms.views import ReportView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/rooms/", include("apps.rooms.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/reports/", ReportView.as_view(), name="report"),
    path("api/wallet/", include("apps.wallet.urls")),
]
