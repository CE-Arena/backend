from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.test import TestCase

from .forms import PlayerSignupForm
from .models import PlayerEmail
from .verification import (
    TOKEN_SALT,
    InvalidVerificationToken,
    activate_verified_email,
    create_verification_token,
)


class EmailVerificationTests(TestCase):

    password = "CEArena-Secure-Test-2026!"

    def create_player(self):
        form = PlayerSignupForm(data={
            "username": "verification_player",
            "email": "verify@example.com",
            "password1": self.password,
            "password2": self.password,
        })

        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_valid_token_activates_account(self):
        user = self.create_player()

        self.assertFalse(user.is_active)

        token = create_verification_token(user)

        payload = signing.loads(
            token,
            salt=TOKEN_SALT,
        )

        self.assertEqual(len(payload["proof"]), 64)

        activated = activate_verified_email(token)

        self.assertEqual(activated.pk, user.pk)

        user.refresh_from_db()

        self.assertTrue(user.is_active)

        identity = PlayerEmail.objects.get(user=user)
        self.assertIsNotNone(identity.verified_at)

        self.assertIsNotNone(
            authenticate(
                username=user.username,
                password=self.password,
            )
        )

    def test_token_cannot_be_reused(self):
        user = self.create_player()
        token = create_verification_token(user)

        activate_verified_email(token)

        with self.assertRaises(InvalidVerificationToken):
            activate_verified_email(token)

    def test_modified_token_is_rejected(self):
        user = self.create_player()
        token = create_verification_token(user)

        modified = (
            ("A" if token[0] != "A" else "B")
            + token[1:]
        )

        with self.assertRaises(InvalidVerificationToken):
            activate_verified_email(modified)

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_expired_token_is_rejected(self):
        user = self.create_player()

        with patch(
            "django.core.signing.time.time",
            return_value=1700000000,
        ):
            token = create_verification_token(user)

        with patch(
            "django.core.signing.time.time",
            return_value=1700000000 + 86401,
        ):
            with self.assertRaises(InvalidVerificationToken):
                activate_verified_email(token)

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_email_change_invalidates_token(self):
        user = self.create_player()
        token = create_verification_token(user)

        user.email = "changed@example.com"
        user.save(update_fields=["email"])

        with self.assertRaises(InvalidVerificationToken):
            activate_verified_email(token)

    def test_password_change_invalidates_token(self):
        user = self.create_player()
        token = create_verification_token(user)

        user.set_password("New-Secure-Password-2026!")
        user.save(update_fields=["password"])

        with self.assertRaises(InvalidVerificationToken):
            activate_verified_email(token)

    def test_regular_active_user_cannot_request_player_token(self):
        User = get_user_model()

        user = User.objects.create_user(
            username="existing_active_user",
            password=self.password,
        )

        with self.assertRaises(InvalidVerificationToken):
            create_verification_token(user)
