from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase

from .forms import PlayerSignupForm


class PlayerActivationTests(TestCase):

    password = "Secure-Test-Password-2026!"

    def test_unverified_player_cannot_login(self):
        form = PlayerSignupForm(data={
            "username": "verification_test_player",
            "email": "verify@example.com",
            "password1": self.password,
            "password2": self.password,
        })

        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()

        self.assertFalse(user.is_active)
        self.assertIsNone(
            user.player_email_identity.verified_at
        )

        authenticated = authenticate(
            username=user.username,
            password=self.password,
        )

        self.assertIsNone(authenticated)

        self.assertFalse(
            self.client.login(
                username=user.username,
                password=self.password,
            )
        )

    def test_normal_django_users_remain_compatible(self):
        User = get_user_model()

        user = User.objects.create_user(
            username="existing_admin_compatible",
            password=self.password,
        )

        self.assertTrue(user.is_active)

        authenticated = authenticate(
            username=user.username,
            password=self.password,
        )

        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated.pk, user.pk)
