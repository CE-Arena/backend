import re

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from .forms import PlayerSignupForm
from .verification import InvalidVerificationToken
from .email_delivery import send_verification_email


@override_settings(
    ROOT_URLCONF="accounts.tests_verification_pages",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="CE ARENA <verify@arena.example.test>",
    CE_ARENA_PUBLIC_ORIGIN="https://arena.example.test",
)
class VerificationEmailDeliveryTests(TestCase):

    password = "CEArena-Secure-Test-2026!"

    def setUp(self):
        form = PlayerSignupForm(data={
            "username": "email_test_player",
            "email": "PLAYER@example.com",
            "password1": self.password,
            "password2": self.password,
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.user = form.save()

    def test_verification_email_is_created(self):
        result = send_verification_email(self.user)

        self.assertEqual(result, 1)
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]

        self.assertEqual(
            email.to,
            ["player@example.com"],
        )

        self.assertEqual(
            email.subject,
            "Verify your CE ARENA account",
        )

        self.assertIn(
            "https://arena.example.test/accounts/verify/",
            email.body,
        )

        self.assertIn("24 hours", email.body)
        self.assertNotIn(self.password, email.body)

    def test_email_contains_valid_verification_link(self):
        send_verification_email(self.user)

        body = mail.outbox[0].body

        match = re.search(
            r"https://arena\.example\.test(/accounts/verify/[^\s]+)",
            body,
        )

        self.assertIsNotNone(match)

        path = match.group(1)

        response = self.client.get(
            path,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()

        # Opening a link must not activate an account.
        self.assertFalse(self.user.is_active)

    def test_insecure_origin_is_rejected(self):
        with override_settings(
            CE_ARENA_PUBLIC_ORIGIN="http://arena.example.test"
        ):
            with self.assertRaises(ImproperlyConfigured):
                send_verification_email(self.user)

        self.assertEqual(len(mail.outbox), 0)

    def test_missing_sender_is_rejected(self):
        with override_settings(
            DEFAULT_FROM_EMAIL="webmaster@localhost"
        ):
            with self.assertRaises(ImproperlyConfigured):
                send_verification_email(self.user)

        self.assertEqual(len(mail.outbox), 0)

    def test_active_account_cannot_request_token(self):
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(InvalidVerificationToken):
            send_verification_email(self.user)

        self.assertEqual(len(mail.outbox), 0)
