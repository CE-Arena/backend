from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from arena.models import Entry, Tournament


class TournamentOwnershipTests(TestCase):

    def setUp(self):
        now = timezone.now()

        self.tournament = Tournament.objects.create(
            title="CE ARENA Ownership Test",
            game="free-fire",
            status=Tournament.Status.OPEN,
            format_label="Solo competition",
            team_size=1,
            capacity=10,
            start_at=now + timedelta(days=4),
            registration_deadline=now + timedelta(days=2),
            rules="Players must follow tournament rules.",
            entry_terms="Free entry",
        )

        self.url = reverse(
            "arena:register",
            args=[self.tournament.pk],
        )

    def make_user(self, username):
        return get_user_model().objects.create_user(
            username=username,
            email=username + "@example.com",
            password="CEArena-Test-Password-2026!",
        )

    def registration_data(self):
        response = self.client.get(
            self.url,
            secure=True,
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)

        token = (
            response.context["form"]["submission_token"].value()
        )

        return {
            "gaming_name": "OwnershipPlayer",
            "player_id": "PLAYER-OWNERSHIP-001",
            "rules_accepted": "on",
            "submission_token": token,
            "roster-TOTAL_FORMS": "0",
            "roster-INITIAL_FORMS": "0",
            "roster-MIN_NUM_FORMS": "0",
            "roster-MAX_NUM_FORMS": "0",
        }

    def submit(self, data):
        return self.client.post(
            self.url,
            data,
            secure=True,
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )

    def test_authenticated_registration_links_account(self):
        user = self.make_user("ownership_player_one")

        self.client.force_login(user)

        data = self.registration_data()
        response = self.submit(data)

        self.assertEqual(response.status_code, 303)

        entry = Entry.objects.get(
            tournament=self.tournament
        )

        self.assertEqual(entry.registered_by_id, user.pk)
        self.assertEqual(entry.status, Entry.Status.PENDING)

    def test_anonymous_registration_remains_anonymous(self):
        data = self.registration_data()

        response = self.submit(data)

        self.assertEqual(response.status_code, 303)

        entry = Entry.objects.get(
            tournament=self.tournament
        )

        self.assertIsNone(entry.registered_by_id)

    def test_same_account_resubmission_is_idempotent(self):
        user = self.make_user("ownership_player_two")

        self.client.force_login(user)

        data = self.registration_data()

        first = self.submit(data)
        second = self.submit(data)

        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)

        self.assertEqual(
            first["Location"],
            second["Location"],
        )

        self.assertEqual(Entry.objects.count(), 1)

        entry = Entry.objects.get()
        self.assertEqual(entry.registered_by_id, user.pk)

    def test_different_account_cannot_reuse_submission(self):
        first_user = self.make_user("ownership_player_three")
        second_user = self.make_user("ownership_player_four")

        self.client.force_login(first_user)

        data = self.registration_data()
        response = self.submit(data)

        self.assertEqual(response.status_code, 303)

        self.client.force_login(second_user)

        replay = self.submit(data)

        self.assertEqual(replay.status_code, 409)
        self.assertEqual(Entry.objects.count(), 1)

        entry = Entry.objects.get()

        self.assertEqual(
            entry.registered_by_id,
            first_user.pk,
        )

    def test_existing_guest_entry_is_not_claimed(self):
        data = self.registration_data()

        response = self.submit(data)
        self.assertEqual(response.status_code, 303)

        entry = Entry.objects.get()
        self.assertIsNone(entry.registered_by_id)

        user = self.make_user("later_signed_in_player")
        self.client.force_login(user)

        entry.refresh_from_db()

        self.assertIsNone(entry.registered_by_id)

    def test_client_cannot_forge_account_ownership(self):
        user = self.make_user("ownership_target_player")

        data = self.registration_data()
        data["registered_by"] = str(user.pk)

        response = self.submit(data)

        self.assertEqual(response.status_code, 303)

        entry = Entry.objects.get()
        self.assertIsNone(entry.registered_by_id)
