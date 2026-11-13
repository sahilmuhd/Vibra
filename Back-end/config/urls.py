from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

from apps.rooms.views import ReportView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/rooms/", include("apps.rooms.urls")),
    path("api/dms/", include("apps.dms.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/perks/", include("apps.perks.urls")),
    path("api/social/", include("apps.social.urls")),
    path("api/games/", include("apps.games.urls")),
    path("api/reports/", ReportView.as_view(), name="report"),
    path("api/wallet/", include("apps.wallet.urls")),
]

# Profile pictures. Served by Django in every environment: they are small,
# cached by the browser, and this avoids touching the certbot-managed nginx file.
def serve_avatar(request, name):
    # MEDIA_ROOT is read per request (not frozen at import), so overrides work.
    return serve(request, name, document_root=settings.MEDIA_ROOT / "avatars")


def serve_voice(request, name):
    return serve(request, name, document_root=settings.MEDIA_ROOT / "voice")


urlpatterns += [
    re_path(r"^media/avatars/(?P<name>[A-Za-z0-9_\-]+\.jpg)$", serve_avatar),
    re_path(r"^media/voice/(?P<name>[A-Za-z0-9_\-]+\.(?:webm|ogg|mp3|m4a|wav))$", serve_voice),
]
