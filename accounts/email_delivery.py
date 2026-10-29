from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.urls import reverse

from .verification import create_verification_token


def send_verification_email(user):
    origin = getattr(
        settings,
        "CE_ARENA_PUBLIC_ORIGIN",
        "",
    ).strip().rstrip("/")

    parsed = urlsplit(origin)

    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ImproperlyConfigured(
            "A valid HTTPS public origin is required."
        )

    sender = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "",
    )

    if not sender or sender == "webmaster@localhost":
        raise ImproperlyConfigured(
            "A real sender email address must be configured."
        )

    token = create_verification_token(user)

    verification_path = reverse(
        "accounts:verify_link",
        args=[token],
    )

    verification_url = origin + verification_path

    subject = "Verify your CE ARENA account"

    message = (
        f"Hello {user.username},\n\n"
        "Welcome to CE ARENA!\n\n"
        "Please verify your email address by opening "
        "the following link:\n\n"
        f"{verification_url}\n\n"
        "This verification link expires after 24 hours.\n\n"
        "If you did not create this account, "
        "you can ignore this message.\n\n"
        "CE ARENA\n"
        "Play. Compete. Connect."
    )

    sent = send_mail(
        subject=subject,
        message=message,
        from_email=sender,
        recipient_list=[user.email],
        fail_silently=False,
    )

    if sent != 1:
        raise RuntimeError(
            "Verification email was not accepted for delivery."
        )

    return sent
