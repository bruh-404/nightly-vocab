"""Root URL configuration."""
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import include, path


from django.conf import settings

def healthz_view(request: HttpRequest) -> HttpResponse:
    """Trivial health check endpoint for reverse proxy / orchestration."""
    return HttpResponse("OK", content_type="text/plain", status=200)

def home_view(request: HttpRequest) -> HttpResponse:
    """Landing view: redirects authenticated users to dashboard."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    return render(request, "home.html", {
        "title": "Nightly Vocab",
        "debug": settings.DEBUG,
    })

def dev_login_view(request: HttpRequest) -> HttpResponse:
    """Convenience login for local development/demo when DEBUG is True."""
    if not settings.DEBUG:
        from django.http import Http404
        raise Http404("صفحه مورد نظر یافت نشد.")
    from django.contrib.auth import get_user_model, login
    User = get_user_model()
    admin_user = User.objects.filter(is_superuser=True).first()
    if admin_user:
        login(request, admin_user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("accounts:dashboard")


from django.views.generic.base import RedirectView

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url="/static/img/favicon.ico", permanent=False)),
    path("admin/", admin.site.urls),
    path("dev-login/", dev_login_view, name="dev_login"),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.cards.urls")),
    path("", include("apps.texts.urls")),
    path("", include("apps.review.urls")),
    path("", include("apps.telegram_bot.urls")),
    path("", include("apps.services.urls")),
    path("healthz/", healthz_view, name="healthz"),
    path("", home_view, name="home"),
]
