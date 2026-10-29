from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import PlayerEmail, normalize_player_email


TOKEN_SALT = "ce-arena-player-email-verification-v1"
TOKEN_MAX_AGE = 24 * 60 * 60


class InvalidVerificationToken(Exception):
    pass


def _email_proof(user, email):
    value = (
        f"{user.pk}:"
        f"{normalize_player_email(email)}:"
        f"{user.password}"
    )

    return salted_hmac(
        "ce-arena-email-verification-proof-v1",
        value,
        algorithm="sha256",
    ).hexdigest()


def create_verification_token(user):
    try:
        identity = PlayerEmail.objects.get(user_id=user.pk)
    except PlayerEmail.DoesNotExist:
        raise InvalidVerificationToken(
            "Email verification is unavailable."
        ) from None

    if (
        user.is_active
        or identity.verified_at is not None
        or normalize_player_email(user.email)
        != identity.normalized_email
    ):
        raise InvalidVerificationToken(
            "Email verification is unavailable."
        )

    return signing.dumps(
        {
            "uid": user.pk,
            "proof": _email_proof(
                user,
                identity.normalized_email,
            ),
        },
        salt=TOKEN_SALT,
    )


def activate_verified_email(token):
    error = "Invalid or expired verification link."

    if not isinstance(token, str) or not 1 <= len(token) <= 1500:
        raise InvalidVerificationToken(error)

    try:
        payload = signing.loads(
            token,
            salt=TOKEN_SALT,
            max_age=TOKEN_MAX_AGE,
        )
    except (signing.BadSignature, ValueError, TypeError):
        raise InvalidVerificationToken(error) from None

    if not isinstance(payload, dict):
        raise InvalidVerificationToken(error)

    uid = payload.get("uid")
    proof = payload.get("proof")

    if (
        not isinstance(uid, int)
        or isinstance(uid, bool)
        or uid <= 0
        or not isinstance(proof, str)
        or len(proof) != 64
    ):
        raise InvalidVerificationToken(error)

    with transaction.atomic():
        identity = (
            PlayerEmail.objects
            .select_related("user")
            .filter(user_id=uid)
            .first()
        )

        if identity is None:
            raise InvalidVerificationToken(error)

        user = identity.user

        if (
            identity.verified_at is not None
            or user.is_active
            or normalize_player_email(user.email)
            != identity.normalized_email
            or not constant_time_compare(
                proof,
                _email_proof(
                    user,
                    identity.normalized_email,
                ),
            )
        ):
            raise InvalidVerificationToken(error)

        updated = PlayerEmail.objects.filter(
            pk=identity.pk,
            verified_at__isnull=True,
        ).update(
            verified_at=timezone.now(),
        )

        if updated != 1:
            raise InvalidVerificationToken(error)

        user.is_active = True
        user.save(update_fields=["is_active"])

        return user
