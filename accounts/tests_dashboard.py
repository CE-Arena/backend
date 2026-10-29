from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from arena.models import Entry, Tournament


class PlayerDashboardTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.player = User.objects.create_user(
            username="dashboard_player",
            password="CEArena-Dashboard-Test-2026!",
        )

        self.other = User.objects.create_user(
            username="another_dashboard_player",
            password="CEArena-Other-Test-2026!",
        )

        self.tournament = Tournament.objects.create(
            title="CE ARENA Dashboard Test",
            game="free-fire",
            status=Tournament.Status.DRAFT,
        )

        self.url = reverse("dashboard")

    def create_entry(self, name, owner, status=Entry.Status.PENDING):
        return Entry.objects.create(
            tournament=self.tournament,
            registered_by=owner,
            gaming_name=name,
            player_id="ID-" + uuid4().hex[:12],
            status=status,
            rules_snapshot="Test rules",
            entry_terms_snapshot="Free entry",
            format_snapshot="Solo",
            submission_key=uuid4(),
        )

    def test_anonymous_user_cannot_access_dashboard(self):
        response = self.client.get(
            self.url,
            secure=True,
        )

        self.assertEqual(response.status_code, 302)

        self.assertIn(
            "/accounts/login/",
            response["Location"],
        )

    def test_player_sees_only_own_registrations(self):
        mine = self.create_entry(
            "MY_PRIVATE_ENTRY",
            self.player,
            Entry.Status.APPROVED,
        )

        someone_else = self.create_entry(
            "OTHER_PRIVATE_ENTRY",
            self.other,
        )

        guest = self.create_entry(
            "GUEST_PRIVATE_ENTRY",
            None,
        )

        self.client.force_login(self.player)

        response = self.client.get(
            self.url,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "MY_PRIVATE_ENTRY",
        )

        self.assertContains(
            response,
            "Approved",
        )

        self.assertContains(
            response,
            mine.get_absolute_url(),
        )

        self.assertNotContains(
            response,
            "OTHER_PRIVATE_ENTRY",
        )

        self.assertNotContains(
            response,
            "GUEST_PRIVATE_ENTRY",
        )

        self.assertNotContains(
            response,
            someone_else.get_absolute_url(),
        )

        self.assertNotContains(
            response,
            guest.get_absolute_url(),
        )

        self.assertEqual(
            list(response.context["entries"]),
            [mine],
        )

    def test_empty_dashboard_has_no_registrations(self):
        self.create_entry(
            "SOMEONE_ELSES_ENTRY",
            self.other,
        )

        self.client.force_login(self.player)

        response = self.client.get(
            self.url,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "No tournament registrations are linked",
        )

        self.assertNotContains(
            response,
            "SOMEONE_ELSES_ENTRY",
        )

    def test_dashboard_disables_caching(self):
        self.client.force_login(self.player)

        response = self.client.get(
            self.url,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "no-store",
            response["Cache-Control"],
        )
