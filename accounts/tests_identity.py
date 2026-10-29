from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from .forms import PlayerSignupForm
from .models import PlayerEmail


class PlayerIdentityTests(TestCase):

    password = "B4r!x-Long&Unique9"

    def make_form(self, username, email):
        return PlayerSignupForm(data={
            "username": username,
            "email": email,
            "password1": self.password,
            "password2": self.password,
        })

    def test_creating_player_creates_email_identity(self):
        form = self.make_form(
            "arena_player_1",
            "PLAYER@Example.COM"
        )

        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()

        identity = PlayerEmail.objects.get(user=user)

        self.assertEqual(user.email, "player@example.com")
        self.assertEqual(
            identity.normalized_email,
            "player@example.com"
        )
        self.assertIsNone(identity.verified_at)
        self.assertTrue(user.check_password(self.password))

    def test_duplicate_email_is_rejected(self):
        first = self.make_form(
            "arena_player_1",
            "Player@Example.com"
        )

        self.assertTrue(first.is_valid(), first.errors)
        first.save()

        second = self.make_form(
            "arena_player_2",
            "player@example.COM"
        )

        self.assertFalse(second.is_valid())
        self.assertIn("email", second.errors)

        self.assertEqual(PlayerEmail.objects.count(), 1)

    def test_database_enforces_email_uniqueness(self):
        User = get_user_model()

        user1 = User.objects.create_user(
            username="identity_test_1",
            password=self.password
        )

        user2 = User.objects.create_user(
            username="identity_test_2",
            password=self.password
        )

        PlayerEmail.objects.create(
            user=user1,
            normalized_email="UNIQUE@example.com"
        )

        with self.assertRaises(IntegrityError):
            from django.db import transaction

            with transaction.atomic():
                PlayerEmail.objects.create(
                    user=user2,
                    normalized_email="unique@example.com"
                )

        self.assertEqual(PlayerEmail.objects.count(), 1)

    def test_atomic_rollback_on_email_conflict(self):
        User = get_user_model()

        form = self.make_form(
            "new_race_player",
            "race@example.com"
        )

        self.assertTrue(form.is_valid(), form.errors)

        other = User.objects.create_user(
            username="existing_race_player",
            password=self.password
        )

        PlayerEmail.objects.create(
            user=other,
            normalized_email="RACE@EXAMPLE.COM"
        )

        with self.assertRaises(IntegrityError):
            form.save()

        self.assertFalse(
            User.objects.filter(
                username="new_race_player"
            ).exists()
        )

        self.assertEqual(PlayerEmail.objects.count(), 1)
