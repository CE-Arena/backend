import hashlib
import hmac
import ipaddress
import time
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone

from .models import SubmissionWindow

class ResponsePrivacyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if (
            request.path.startswith("/arena-admin/")
            or request.path.startswith("/tournaments/entry/")
            or request.path.startswith("/accounts/")
            or request.path == "/dashboard/"
            or request.path.endswith("/register/")
        ):
            response["Cache-Control"] = "private, no-store, max-age=0"
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        if request.path.startswith("/tournaments/entry/"):
            # Receipts are GET-only bearer links. Forms retain same-origin
            # referrers for Django's HTTPS CSRF fallback when Origin is absent.
            response["Referrer-Policy"] = "no-referrer"
        return response

def client_address(request):
    address = request.META.get("REMOTE_ADDR", "")
    # The service is loopback-only. Nginx explicitly overwrites X-Real-IP.
    if address in ("127.0.0.1", "::1"):
        address = request.META.get("HTTP_X_REAL_IP", address)
    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        return "unknown"

class SubmissionLimitMiddleware:
    window_seconds = 600
    limits = {"registration": 30, "login": 10, "player_login": 10, "player_signup": 5, "email_resend": 3}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        scope = None
        if request.method == "POST":
            if request.path.startswith("/tournaments/") and request.path.endswith("/register/"):
                scope = "registration"
            elif request.path == "/arena-admin/login/":
                scope = "login"
            elif request.path == "/accounts/login/":
                scope = "player_login"
            elif request.path == "/accounts/register/":
                scope = "player_signup"
            elif request.path == "/accounts/resend-verification/":
                scope = "email_resend"
        if scope:
            now = timezone.now()
            window = int(time.time()) // self.window_seconds
            message = f"{scope}:{window}:{client_address(request)}".encode()
            key = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()
            try:
                with transaction.atomic():
                    SubmissionWindow.objects.filter(expires_at__lt=now).delete()
                    counter, _ = SubmissionWindow.objects.get_or_create(key=key, defaults={"expires_at": now + timedelta(seconds=self.window_seconds)})
                    limited = counter.count >= self.limits[scope]
                    if not limited:
                        counter.count += 1
                        counter.save(update_fields=("count",))
            except OperationalError:
                from .views import unavailable
                return unavailable(request, "Please try again shortly", "The service is busy. Your submission has not been confirmed.", status=503)
            if limited:
                from .views import unavailable
                response = unavailable(request, "Please wait before trying again", "There have been several recent attempts from this connection. Please wait up to 10 minutes and try again.", status=429)
                response["Retry-After"] = str(self.window_seconds)
                return response
        return self.get_response(request)
