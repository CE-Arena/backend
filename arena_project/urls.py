from django.contrib import admin
from django.urls import include, path
from arena import views

urlpatterns = [
    path("arena-admin/preview/<int:pk>/", admin.site.admin_view(views.admin_preview), name="arena_admin_preview"),
    path("arena-admin/", admin.site.urls),
    path("tournaments/", include("arena.urls")),
]
handler400 = "arena.views.bad_request"
handler403 = "arena.views.permission_denied"
handler404 = "arena.views.not_found"
handler500 = "arena.views.server_error"
