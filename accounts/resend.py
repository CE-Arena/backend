import hashlib
import hmac
import time

from datetime import timedelta
from smtplib import SMTPException

from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, transaction
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from arena.models import SubmissionWindow

from .email_delivery import send_verification_email
from .models import PlayerEmail, normalize_player_email
from .verification import InvalidVerificationToken


class ResendVerificationForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        max_length=254,
    )

    def clean_email(self):
        return normalize_player_email(
            self.cleaned_data["email"]
        )


def allow_email_resend(email):
    """Rate-limit by email without storing the actual address."""

    window = int(time.time()) // 3600

    message = f"email-resend:{window}:{email}".encode()

    key = hmac.new(
        settings.SECRET_KEY.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()

    with transaction.atomic():
        SubmissionWindow.objects.get_or_create(
            key=key,
            defaults={
                "expires_at": timezone.now()
                + timedelta(hours=1)
            },
        )

        updated = SubmissionWindow.objects.filter(
            key=key,
            count__lt=3,
        ).update(
            count=F("count") + 1
        )

    return updated == 1


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def resend_verification(request):

    form = ResendVerificationForm(
        request.POST if request.method == "POST" else None
    )

    if request.method == "POST" and form.is_valid():

        email = form.cleaned_data["email"]

        try:
            allowed = allow_email_resend(email)

            if allowed:
                identity = (
                    PlayerEmail.objects
                    .select_related("user")
                    .filter(
                        normalized_email=email,
                        verified_at__isnull=True,
                    )
                    .first()
                )

                if identity is not None:
                    user = identity.user

                    if (
                        not user.is_active
                        and normalize_player_email(user.email)
                        == email
                    ):
                        try:
                            send_verification_email(user)
                        except (
                            ImproperlyConfigured,
                            SMTPException,
                            OSError,
                            RuntimeError,
                            InvalidVerificationToken,
                        ):
                            # Do not disclose account existence.
                            pass

        except OperationalError:
            # Fail closed if database rate limiting is unavailable.
            pass

        return redirect("accounts:check_email")

    return render(
        request,
        "accounts/resend_verification.html",
        {"form": form},
    )
