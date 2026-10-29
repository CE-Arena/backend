from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="CE ARENA <verify@arena.example.test>",
    CE_ARENA_PUBLIC_ORIGIN="https://arena.example.test",
)
class FullPlayerJourneyTests(TestCase):

    password = "CEArena-Secure-Test-2026!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def get_page(self, path):
        return self.client.get(
            path,
            secure=True,
            HTTP_HOST="localhost",
        )

    def post_form(self, path, data, include_csrf=True):
        data = dict(data)

        if include_csrf:
            data["csrfmiddlewaretoken"] = (
                self.client.cookies[
                    settings.CSRF_COOKIE_NAME
                ].value
            )

        return self.client.post(
            path,
            data,
            secure=True,
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )

    def signup_data(self):
        return {
            "username": "fullflow_player",
            "email": "fullflow@example.com",
            "password1": self.password,
            "password2": self.password,
        }

    def test_complete_player_authentication(self):

        signup = reverse("accounts:signup")
        login = reverse("accounts:login")
        logout = reverse("accounts:logout")
        dashboard = reverse("dashboard")

        # Anonymous players cannot access the dashboard.
        response = self.get_page(dashboard)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

        # Create a new player account.
        self.assertEqual(
            self.get_page(signup).status_code,
            200,
        )

        response = self.post_form(
            signup,
            self.signup_data(),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("accounts:check_email"),
        )

        User = get_user_model()

        user = User.objects.get(
            username="fullflow_player"
        )

        self.assertFalse(user.is_active)
        self.assertIsNone(
            user.player_email_identity.verified_at
        )

        # Email generated without sending real mail.
        self.assertEqual(len(mail.outbox), 1)

        message = mail.outbox[0]

        self.assertEqual(
            message.to,
            ["fullflow@example.com"],
        )

        self.assertNotIn(
            self.password,
            message.body,
        )

        # Extract the HTTPS verification link.
        links = [
            line.strip()
            for line in message.body.splitlines()
            if line.startswith(
                "https://arena.example.test/accounts/verify/"
            )
        ]

        self.assertEqual(len(links), 1)

        verification_url = links[0]
        verification_path = urlsplit(verification_url).path

        token = verification_path.split(
            "/accounts/verify/", 1
        )[1].rstrip("/")

        # Login must fail before email verification.
        self.get_page(login)

        response = self.post_form(
            login,
            {
                "username": user.username,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

        # Opening the verification link is read-only.
        response = self.get_page(verification_path)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Referrer-Policy"],
            "strict-origin",
        )

        user.refresh_from_db()
        self.assertFalse(user.is_active)

        # Explicit confirmation activates the account.
        response = self.post_form(
            reverse("accounts:verify_submit"),
            {"token": token},
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(token, response["Location"])

        user.refresh_from_db()

        self.assertTrue(user.is_active)
        self.assertIsNotNone(
            user.player_email_identity.verified_at
        )

        # The verification token cannot be reused.
        response = self.post_form(
            reverse("accounts:verify_submit"),
            {"token": token},
        )

        self.assertEqual(response.status_code, 400)

        # Verified account can now log in.
        self.get_page(login)

        response = self.post_form(
            login,
            {
                "username": user.username,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            dashboard,
        )

        self.assertIn(
            settings.SESSION_COOKIE_NAME,
            response.cookies,
        )

        self.assertEqual(
            response.cookies[
                settings.SESSION_COOKIE_NAME
            ]["path"],
            "/",
        )

        # Dashboard is now accessible.
        response = self.get_page(dashboard)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "fullflow_player",
        )

        self.assertIn(
            "no-store",
            response["Cache-Control"],
        )

        # Regular players cannot access Django admin.
        response = self.get_page("/arena-admin/")
        self.assertEqual(response.status_code, 302)

        # Logout must use POST.
        response = self.get_page(logout)
        self.assertEqual(response.status_code, 405)

        response = self.post_form(logout, {})

        self.assertEqual(response.status_code, 302)

        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

        # Dashboard is protected again.
        response = self.get_page(dashboard)

        self.assertEqual(response.status_code, 302)

    def test_signup_requires_csrf(self):

        signup = reverse("accounts:signup")

        self.get_page(signup)

        response = self.post_form(
            signup,
            self.signup_data(),
            include_csrf=False,
        )

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            get_user_model().objects.filter(
                username="fullflow_player"
            ).exists()
        )

        self.assertEqual(len(mail.outbox), 0)
