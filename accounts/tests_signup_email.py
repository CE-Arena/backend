from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse


@override_settings(
    ROOT_URLCONF="accounts.tests_verification_pages",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="CE ARENA <verify@arena.example.test>",
    CE_ARENA_PUBLIC_ORIGIN="https://arena.example.test",
)
class SignupEmailTests(TestCase):

    password = "CEArena-Strong-Password-2026!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def submit_signup(self, **changes):
        response = self.client.get(
            reverse("accounts:signup"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        csrf = self.client.cookies[
            settings.CSRF_COOKIE_NAME
        ].value

        data = {
            "username": "new_arena_player",
            "email": "newplayer@example.com",
            "password1": self.password,
            "password2": self.password,
            "csrfmiddlewaretoken": csrf,
        }

        data.update(changes)

        return self.client.post(
            reverse("accounts:signup"),
            data,
            secure=True,
            HTTP_ORIGIN="https://testserver",
        )

    def test_signup_sends_verification_email(self):
        response = self.submit_signup()

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            response["Location"],
            reverse("accounts:check_email"),
        )

        self.assertEqual(len(mail.outbox), 1)

        message = mail.outbox[0]

        self.assertEqual(
            message.to,
            ["newplayer@example.com"],
        )

        self.assertIn(
            "https://arena.example.test/accounts/verify/",
            message.body,
        )

        self.assertNotIn(self.password, message.body)

        user = get_user_model().objects.get(
            username="new_arena_player"
        )

        self.assertFalse(user.is_active)
        self.assertIsNone(
            user.player_email_identity.verified_at
        )

    def test_invalid_signup_sends_no_email(self):
        response = self.submit_signup(
            password2="Incorrect-Password-2026!"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

        self.assertFalse(
            get_user_model().objects.filter(
                username="new_arena_player"
            ).exists()
        )

    @patch(
        "accounts.views.send_verification_email",
        side_effect=OSError("Simulated SMTP outage"),
    )
    def test_email_failure_keeps_account_inactive(self, mocked):
        response = self.submit_signup()

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "could not send the verification email",
        )

        user = get_user_model().objects.get(
            username="new_arena_player"
        )

        self.assertFalse(user.is_active)

        self.assertIsNone(
            user.player_email_identity.verified_at
        )

        mocked.assert_called_once()

    def test_check_email_page(self):
        response = self.client.get(
            reverse("accounts:check_email"),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "Check your inbox",
        )
