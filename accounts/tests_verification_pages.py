from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import include, path, reverse

from .forms import PlayerSignupForm
from .verification import create_verification_token


# Isolated routes: do not activate authentication in the main project.
urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("tournaments/", include("arena.urls")),
]


@override_settings(ROOT_URLCONF="accounts.tests_verification_pages")
class VerificationPageTests(TestCase):

    password = "CEArena-Secure-Test-2026!"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def create_player(self):
        form = PlayerSignupForm(data={
            "username": "page_test_player",
            "email": "page@example.com",
            "password1": self.password,
            "password2": self.password,
        })

        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def open_link(self, token):
        return self.client.get(
            reverse("accounts:verify_link", args=[token]),
            secure=True,
        )

    def confirm(self, token, csrf=True):
        data = {"token": token}

        if csrf:
            data["csrfmiddlewaretoken"] = (
                self.client.cookies[
                    settings.CSRF_COOKIE_NAME
                ].value
            )

        return self.client.post(
            reverse("accounts:verify_submit"),
            data,
            secure=True,
            HTTP_ORIGIN="https://testserver",
        )

    def test_opening_link_does_not_activate_account(self):
        user = self.create_player()
        token = create_verification_token(user)

        response = self.open_link(token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Referrer-Policy"],
            "strict-origin",
        )
        self.assertIn(
            "no-store",
            response["Cache-Control"],
        )

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_confirmation_activates_account(self):
        user = self.create_player()
        token = create_verification_token(user)

        self.open_link(token)
        response = self.confirm(token)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("accounts:verification_complete"),
        )
        self.assertNotIn(token, response["Location"])

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNotNone(
            user.player_email_identity.verified_at
        )

        success = self.client.get(
            reverse("accounts:verification_complete"),
            secure=True,
        )
        self.assertEqual(success.status_code, 200)

    def test_missing_csrf_is_rejected(self):
        user = self.create_player()
        token = create_verification_token(user)

        response = self.confirm(token, csrf=False)

        self.assertEqual(response.status_code, 403)

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_invalid_token_is_rejected(self):
        response = self.open_link("invalid-token")

        self.assertEqual(response.status_code, 200)

        confirmation = self.confirm("invalid-token")

        self.assertEqual(confirmation.status_code, 400)

    def test_reused_token_is_rejected(self):
        user = self.create_player()
        token = create_verification_token(user)

        self.open_link(token)

        first = self.confirm(token)
        second = self.confirm(token)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 400)

    def test_success_page_requires_successful_verification(self):
        response = self.client.get(
            reverse("accounts:verification_complete"),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("accounts:login"),
        )
