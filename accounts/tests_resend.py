from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import PlayerSignupForm


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="CE ARENA <verify@arena.example.test>",
    CE_ARENA_PUBLIC_ORIGIN="https://arena.example.test",
)
class ResendVerificationTests(TestCase):

    password = "CEArena-Resend-Test-2026!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse("accounts:resend_verification")

        self.client.get(
            self.url,
            secure=True,
            HTTP_HOST="localhost",
        )

    def create_player(self):
        form = PlayerSignupForm(data={
            "username": "resend_player",
            "email": "resend@example.com",
            "password1": self.password,
            "password2": self.password,
        })

        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def submit(self, email, ip="192.0.2.100"):
        return self.client.post(
            self.url,
            {
                "email": email,
                "csrfmiddlewaretoken": self.client.cookies[
                    settings.CSRF_COOKIE_NAME
                ].value,
            },
            secure=True,
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
            REMOTE_ADDR=ip,
        )

    def test_unverified_player_receives_email(self):
        user = self.create_player()

        response = self.submit("RESEND@example.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("accounts:check_email"),
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            ["resend@example.com"],
        )

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_unknown_email_has_generic_response(self):
        response = self.submit("unknown@example.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("accounts:check_email"),
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_verified_account_receives_no_email(self):
        user = self.create_player()

        user.is_active = True
        user.save(update_fields=["is_active"])

        response = self.submit("resend@example.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_per_address_limit(self):
        self.create_player()

        for number in range(4):
            response = self.submit(
                "resend@example.com",
                ip=f"192.0.2.{110 + number}",
            )
            self.assertEqual(response.status_code, 302)

        self.assertEqual(len(mail.outbox), 3)

    def test_per_ip_limit(self):
        self.create_player()

        for _ in range(3):
            response = self.submit(
                "resend@example.com",
                ip="192.0.2.120",
            )
            self.assertEqual(response.status_code, 302)

        response = self.submit(
            "resend@example.com",
            ip="192.0.2.120",
        )

        self.assertEqual(response.status_code, 429)

    def test_csrf_required(self):
        self.create_player()

        response = self.client.post(
            self.url,
            {"email": "resend@example.com"},
            secure=True,
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    @patch(
        "accounts.resend.send_verification_email",
        side_effect=OSError("Simulated SMTP outage"),
    )
    def test_delivery_failure_keeps_account_inactive(self, mocked):
        user = self.create_player()

        response = self.submit("resend@example.com")

        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertFalse(user.is_active)

        self.assertEqual(len(mail.outbox), 0)
        mocked.assert_called_once()
