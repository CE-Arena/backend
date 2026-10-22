"""Behavioral checks for public registration and the private organizer workflow.

All data is fictional and stays in Django's isolated test database. HTTP tests
use the actual rendered form tokens and management fields, with HTTPS enabled.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import tournament_revision
from .models import Entry, Participant, Tournament
from .services import DuplicatePlayer, RegistrationUnavailable, create_entry


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RegistrationWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_superuser(
            username="test-organizer", email="organizer@example.invalid",
            password="test-only-organizer-password",
        )
        cls.member = User.objects.create_user(
            username="ordinary-member", password="test-only-member-password",
        )
        cls.staff = User.objects.create_user(
            username="tournament-reviewer", password="test-only-staff-password",
            is_staff=True,
        )
        cls.staff.user_permissions.add(
            Permission.objects.get(codename="view_tournament")
        )

    def make_tournament(self, **overrides):
        now = timezone.now()
        values = {
            "title": "Test Free Fire Tournament",
            "game": "free-fire",
            "status": Tournament.Status.OPEN,
            "format_label": "Solo test competition",
            "team_size": 1,
            "capacity": 12,
            "start_at": now + timedelta(days=2),
            "registration_deadline": now + timedelta(days=1),
            "rules": "Test event rules: attend on time and play fairly.",
            "entry_terms": "Free entry for this test event.",
        }
        values.update(overrides)
        tournament = Tournament(**values)
        tournament.full_clean()
        tournament.save()
        return tournament

    def registration_data(self, tournament, *, client=None,
                          player_id="CAPTAIN-001", gaming_name="Test Captain",
                          team_name="Test Squad", teammates=None):
        """Build a submission using only management inputs the page renders."""
        client = client or self.client
        response = client.get(
            reverse("arena:register", args=(tournament.pk,)), secure=True,
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        data = {
            "gaming_name": gaming_name,
            "player_id": player_id,
            "rules_accepted": "on",
            "website": "",
            "submission_token": form["submission_token"].value(),
        }
        if tournament.team_size > 1:
            data["team_name"] = team_name
        roster = response.context["roster"]
        html = response.content.decode()
        for field in roster.management_form:
            if f'name="{field.html_name}"' in html:
                data[field.html_name] = str(field.value())
        if teammates is None:
            teammates = [
                {"gaming_name": f"Test Teammate {position}",
                 "player_id": f"{player_id}-MATE-{position}"}
                for position in range(1, tournament.team_size)
            ]
        for index, player in enumerate(teammates):
            for name, value in player.items():
                data[f"{roster.prefix}-{index}-{name}"] = value
        return data

    def submit(self, tournament, data, *, client=None, **kwargs):
        return (client or self.client).post(
            reverse("arena:register", args=(tournament.pk,)),
            data, secure=True, **kwargs,
        )

    def assert_not_registered(self, response, *, entries=0, statuses=(200, 400, 409)):
        self.assertIn(response.status_code, statuses)
        self.assertEqual(Entry.objects.count(), entries)
        self.assertNotIn("/entry/", response.headers.get("Location", ""))

    def service_entry(self, tournament, *, player_id="SERVICE-001", teammates=None):
        return create_entry(
            tournament.pk,
            {"gaming_name": f"Player {player_id}", "player_id": player_id,
             "team_name": "Service Squad" if tournament.team_size > 1 else "",
             "rules_accepted": True},
            teammates or [], uuid.uuid4(), tournament_revision(tournament),
        )

    def admin_review(self, entry, status, note="Private test review note"):
        self.client.force_login(self.owner)
        url = reverse("admin:arena_entry_change", args=(entry.pk,))
        page = self.client.get(url, secure=True)
        self.assertEqual(page.status_code, 200)
        data = {"status": status, "internal_note": note, "_save": "Save"}
        for inline in page.context["inline_admin_formsets"]:
            formset = inline.formset
            for field in formset.management_form:
                data[field.html_name] = str(field.value())
            for form in formset:
                for field in form.hidden_fields():
                    if field.value() is not None:
                        data[field.html_name] = str(field.value())
        return self.client.post(
            url, data, secure=True,
        )

    def test_incomplete_draft_cannot_be_published(self):
        draft = Tournament.objects.create(title="Unannounced test draft")
        draft.status = Tournament.Status.OPEN
        with self.assertRaises(ValidationError) as caught:
            draft.full_clean()
        self.assertTrue(
            {"format_label", "capacity", "start_at", "registration_deadline",
             "rules", "entry_terms"}.issubset(caught.exception.message_dict)
        )
        draft.refresh_from_db()
        self.assertEqual(draft.status, Tournament.Status.DRAFT)

    def test_opening_requires_future_dates_and_a_valid_deadline(self):
        tournament = self.make_tournament(status=Tournament.Status.DRAFT)
        tournament.status = Tournament.Status.OPEN
        tournament.registration_deadline = timezone.now() - timedelta(seconds=1)
        with self.assertRaises(ValidationError):
            tournament.full_clean()
        tournament.registration_deadline = tournament.start_at + timedelta(minutes=1)
        with self.assertRaises(ValidationError):
            tournament.full_clean()

    def test_admin_cannot_publish_an_incomplete_draft(self):
        draft = Tournament.objects.create(title="Incomplete admin publication test")
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("admin:arena_tournament_change", args=(draft.pk,)),
            {"title": draft.title, "game": "free-fire", "status": "open",
             "team_size": "1", "capacity": "", "format_label": "",
             "entry_terms": "", "prize_details": "", "rules": "",
             "start_at_0": "", "start_at_1": "",
             "registration_deadline_0": "", "registration_deadline_1": "",
             "_save": "Save"}, secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["adminform"].form.errors)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Tournament.Status.DRAFT)
        self.assertEqual(self.client.get(draft.get_absolute_url(), secure=True).status_code, 404)

    def test_drafts_are_hidden_from_public_lists_details_and_registration(self):
        draft = Tournament.objects.create(title="PRIVATE UNANNOUNCED TEST EVENT")
        for path in ("/tournaments/", "/tournaments/game/free-fire/"):
            response = self.client.get(path, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, draft.title)
        for path in (f"/tournaments/{draft.pk}/", f"/tournaments/{draft.pk}/register/"):
            self.assertEqual(self.client.get(path, secure=True).status_code, 404)

    def test_game_listing_filters_events_and_rejects_unknown_games(self):
        event = self.make_tournament(title="Visible Free Fire test event")
        other = self.make_tournament(title="Visible Valorant test event", game="valorant")
        response = self.client.get("/tournaments/game/free-fire/", secure=True)
        self.assertContains(response, event.title)
        self.assertNotContains(response, other.title)
        self.assertEqual(
            self.client.get("/tournaments/game/not-a-real-game/", secure=True).status_code,
            404,
        )

    def test_admin_and_draft_preview_require_an_authorized_staff_account(self):
        draft = Tournament.objects.create(title="Private preview test")
        preview = f"/arena-admin/preview/{draft.pk}/"
        for path in ("/arena-admin/", preview):
            response = self.client.get(path, secure=True)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/arena-admin/login/", response["Location"])
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(preview, secure=True).status_code, 302)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(preview, secure=True), draft.title)

    def test_registration_saves_pending_entry_before_receipt(self):
        tournament = self.make_tournament()
        response = self.submit(tournament, self.registration_data(tournament))
        self.assertEqual(response.status_code, 303)
        entry = Entry.objects.get()
        self.assertEqual(entry.status, Entry.Status.PENDING)
        self.assertEqual(entry.tournament, tournament)
        self.assertEqual(entry.rules_snapshot, tournament.rules)
        self.assertEqual(entry.entry_terms_snapshot, tournament.entry_terms)
        self.assertEqual(entry.format_snapshot, tournament.format_label)
        self.assertEqual(list(entry.participants.values_list("player_id", flat=True)), ["CAPTAIN-001"])
        self.assertEqual(response["Location"], entry.get_absolute_url())
        self.assertContains(self.client.get(response["Location"], secure=True), entry.reference)

    def test_staff_with_preview_permission_cannot_approve_entries_without_change_permission(self):
        tournament = self.make_tournament()
        entry = self.service_entry(tournament)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("admin:arena_entry_change", args=(entry.pk,)),
            {"status": "approved", "internal_note": "Unauthorized test change", "_save": "Save"},
            secure=True,
        )
        self.assertEqual(response.status_code, 403)
        entry.refresh_from_db()
        self.assertEqual(entry.status, Entry.Status.PENDING)
        self.assertEqual(entry.internal_note, "")

    def test_required_details_and_rules_consent_do_not_create_entries(self):
        tournament = self.make_tournament()
        for field in ("gaming_name", "player_id", "rules_accepted"):
            with self.subTest(field=field):
                data = self.registration_data(tournament)
                data[field] = ""
                self.assert_not_registered(self.submit(tournament, data))
        self.assertEqual(Participant.objects.count(), 0)

    def test_unicode_expansion_obeys_field_limits_and_normalized_names_are_accepted(self):
        tournament = self.make_tournament(team_size=2)
        # The ligature is one input character but becomes three under NFKC.
        for field, repetitions in (("gaming_name", 21), ("player_id", 27), ("team_name", 27)):
            with self.subTest(field=field):
                data = self.registration_data(tournament)
                data[field] = "\ufb03" * repetitions
                response = self.submit(tournament, data)
                self.assert_not_registered(response)
                self.assertIn(field, response.context["form"].errors)

        normal = self.registration_data(
            tournament, gaming_name="Ｅｄｄｙ　Ｆｉｒｅ", player_id="ＵＩＤ-１２３",
            team_name="ＣＥ　Ｓｑｕａｄ",
            teammates=[{"gaming_name": "Ｍａｔｅ", "player_id": "ＵＩＤ-４５６"}],
        )
        self.assertEqual(self.submit(tournament, normal).status_code, 303)
        entry = Entry.objects.get()
        self.assertEqual((entry.gaming_name, entry.player_id, entry.team_name),
                         ("Eddy Fire", "UID-123", "CE Squad"))
        self.assertEqual(list(entry.participants.values_list("player_id", flat=True)),
                         ["UID-123", "UID-456"])

    def test_honeypot_does_not_show_a_false_success_or_save_an_entry(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        data["website"] = "https://example.invalid/bot"
        self.assert_not_registered(self.submit(tournament, data))

    def test_signed_form_cannot_be_tampered_with_or_moved_to_another_tournament(self):
        tournament = self.make_tournament()
        other = self.make_tournament(title="Another test tournament")
        data = self.registration_data(tournament)
        self.assert_not_registered(self.submit(other, data))
        data["submission_token"] += "tampered"
        self.assert_not_registered(self.submit(tournament, data))

    def test_public_fields_cannot_set_approval_or_private_organizer_notes(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        data.update(status="approved", internal_note="FORGED ORGANIZER NOTE")
        response = self.submit(tournament, data)
        self.assertEqual(response.status_code, 303)
        entry = Entry.objects.get()
        self.assertEqual(entry.status, Entry.Status.PENDING)
        self.assertEqual(entry.internal_note, "")
        self.assertIsNone(entry.reviewed_by)

    def test_deadline_is_rechecked_after_the_form_has_been_opened(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        Tournament.objects.filter(pk=tournament.pk).update(
            registration_deadline=timezone.now() - timedelta(seconds=1),
        )
        self.assert_not_registered(self.submit(tournament, data))

    def test_closed_tournament_rejects_a_form_obtained_while_open(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.CLOSED)
        self.assert_not_registered(self.submit(tournament, data))

    def test_last_available_place_cannot_be_used_by_two_previously_opened_forms(self):
        tournament = self.make_tournament(capacity=1)
        first = self.registration_data(tournament, player_id="FIRST-PLAYER")
        second = self.registration_data(tournament, player_id="SECOND-PLAYER")
        self.assertEqual(self.submit(tournament, first).status_code, 303)
        self.assert_not_registered(self.submit(tournament, second), entries=1)
        self.assertEqual(tournament.active_entry_count(), 1)
        self.assertFalse(Participant.objects.filter(player_id="SECOND-PLAYER").exists())

    def test_identical_resubmission_returns_the_same_receipt_even_when_full(self):
        tournament = self.make_tournament(capacity=1)
        data = self.registration_data(tournament)
        first = self.submit(tournament, data)
        second = self.submit(tournament, data)
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)
        self.assertEqual(first["Location"], second["Location"])
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Participant.objects.count(), 1)

    def test_used_submission_token_cannot_be_repurposed_for_another_player(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        self.assertEqual(self.submit(tournament, data).status_code, 303)
        data["player_id"] = "DIFFERENT-PLAYER"
        self.assert_not_registered(self.submit(tournament, data), entries=1)
        self.assertEqual(Entry.objects.get().player_id, "CAPTAIN-001")

    def test_rule_changes_require_the_player_to_review_a_fresh_form(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        tournament.rules = "Changed test rules that were not on the submitted form."
        tournament.save(update_fields=["rules"])
        self.assert_not_registered(self.submit(tournament, data))
        fresh = self.registration_data(tournament)
        self.assertEqual(self.submit(tournament, fresh).status_code, 303)
        self.assertEqual(Entry.objects.get().rules_snapshot, tournament.rules)

    def test_existing_entry_keeps_the_rules_originally_accepted(self):
        tournament = self.make_tournament()
        entry = self.service_entry(tournament)
        accepted_rules = entry.rules_snapshot
        tournament.rules = "Later organizer amendment to the test rules."
        tournament.save(update_fields=["rules"])
        entry.refresh_from_db()
        self.assertEqual(entry.rules_snapshot, accepted_rules)

    def test_receipts_and_public_pages_do_not_expose_private_notes_or_other_players(self):
        tournament = self.make_tournament()
        first = self.service_entry(tournament, player_id="PRIVATE-FIRST-PLAYER-UID")
        second = self.service_entry(tournament, player_id="PRIVATE-SECOND-PLAYER-UID")
        first.internal_note = "ORGANIZER-ONLY-TEST-NOTE"
        first.save(update_fields=["internal_note"])
        receipt = self.client.get(first.get_absolute_url(), secure=True)
        self.assertContains(receipt, first.reference)
        self.assertNotContains(receipt, first.internal_note)
        self.assertNotContains(receipt, second.player_id)
        self.assertNotContains(receipt, second.reference)
        self.assertIn("no-store", receipt.get("Cache-Control", ""))
        self.assertEqual(receipt.get("Referrer-Policy"), "no-referrer")
        for path in ("/tournaments/", "/tournaments/game/free-fire/", tournament.get_absolute_url()):
            public = self.client.get(path, secure=True)
            self.assertNotContains(public, first.player_id)
            self.assertNotContains(public, second.player_id)
            self.assertNotContains(public, first.reference)

    def test_unknown_receipts_return_404_instead_of_any_existing_entry(self):
        tournament = self.make_tournament()
        entry = self.service_entry(tournament)
        for path in (f"/tournaments/entry/{uuid.uuid4()}/", f"/tournaments/entry/{entry.pk}/"):
            response = self.client.get(path, secure=True)
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, entry.reference, status_code=404)

    def test_participant_write_failure_rolls_back_the_pending_entry(self):
        tournament = self.make_tournament()
        with patch("arena.services.Participant.objects.bulk_create", side_effect=IntegrityError("test conflict")):
            with self.assertRaises(DuplicatePlayer):
                self.service_entry(tournament)
        self.assertEqual(Entry.objects.count(), 0)
        self.assertEqual(Participant.objects.count(), 0)

    def test_team_entry_saves_the_captain_and_exact_announced_roster(self):
        tournament = self.make_tournament(team_size=3, format_label="Three-player test teams")
        response = self.submit(tournament, self.registration_data(tournament))
        self.assertEqual(response.status_code, 303)
        entry = Entry.objects.get()
        self.assertEqual(entry.team_name, "Test Squad")
        self.assertEqual(entry.participants.count(), 3)
        self.assertEqual(entry.participants.first().player_id, entry.player_id)
        self.assertEqual(Participant.objects.filter(tournament=tournament).count(), 3)

    def test_missing_or_forged_team_management_fields_never_create_partial_entries(self):
        tournament = self.make_tournament(team_size=3)
        for total in (None, "0", "1", "1000000", "not-an-integer"):
            with self.subTest(total=total):
                data = self.registration_data(tournament)
                if total is None:
                    data = {key: value for key, value in data.items() if key not in (
                        "roster-TOTAL_FORMS", "roster-INITIAL_FORMS", "roster-MIN_NUM_FORMS", "roster-MAX_NUM_FORMS",
                    )}
                else:
                    data["roster-TOTAL_FORMS"] = total
                self.assert_not_registered(self.submit(tournament, data))
        self.assertEqual(Participant.objects.count(), 0)

    def test_team_name_and_every_teammates_fields_are_required(self):
        tournament = self.make_tournament(team_size=3)
        for field in ("team_name", "roster-0-gaming_name", "roster-1-player_id"):
            with self.subTest(field=field):
                data = self.registration_data(tournament)
                data[field] = ""
                self.assert_not_registered(self.submit(tournament, data))

    def test_a_captain_cannot_also_be_a_teammate_with_case_or_unicode_variations(self):
        tournament = self.make_tournament(team_size=2)
        data = self.registration_data(
            tournament, player_id="Alpha-123",
            teammates=[{"gaming_name": "Same player", "player_id": "ＡＬＰＨＡ-123"}],
        )
        self.assert_not_registered(self.submit(tournament, data))
        self.assertEqual(Participant.objects.count(), 0)

    def test_existing_captains_and_teammates_cannot_join_another_team_in_that_event(self):
        tournament = self.make_tournament(team_size=2)
        first = self.registration_data(
            tournament, player_id="CAPTAIN-A",
            teammates=[{"gaming_name": "First teammate", "player_id": "MATE-B"}],
        )
        self.assertEqual(self.submit(tournament, first).status_code, 303)
        cases = (
            ("mate-b", "NEW-MATE"),
            ("NEW-CAPTAIN", "ｃａｐｔａｉｎ-ａ"),
        )
        for captain, mate in cases:
            with self.subTest(captain=captain, mate=mate):
                data = self.registration_data(
                    tournament, player_id=captain,
                    teammates=[{"gaming_name": "New teammate", "player_id": mate}],
                )
                self.assert_not_registered(self.submit(tournament, data), entries=1)
        self.assertEqual(Participant.objects.count(), 2)

    def test_player_uniqueness_is_per_tournament_not_global(self):
        first = self.make_tournament()
        second = self.make_tournament(title="Second independently entered test event")
        self.service_entry(first, player_id="SHARED-PLAYER")
        self.service_entry(second, player_id="SHARED-PLAYER")
        self.assertEqual(Entry.objects.count(), 2)

    def test_approval_keeps_a_reserved_place_and_rejection_frees_it(self):
        tournament = self.make_tournament(capacity=1)
        entry = self.service_entry(tournament)
        self.assertEqual(self.admin_review(entry, Entry.Status.APPROVED).status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.status, Entry.Status.APPROVED)
        self.assertEqual(entry.reviewed_by, self.owner)
        self.assertIsNotNone(entry.reviewed_at)
        self.assertEqual(tournament.active_entry_count(), 1)
        self.assertEqual(self.admin_review(entry, Entry.Status.REJECTED).status_code, 302)
        self.assertEqual(tournament.active_entry_count(), 0)
        self.service_entry(tournament, player_id="NEW-PLAYER")
        self.assertEqual(tournament.active_entry_count(), 1)

    def test_organizer_cannot_restore_a_rejected_entry_when_another_entry_fills_capacity(self):
        tournament = self.make_tournament(capacity=1)
        rejected = self.service_entry(tournament)
        self.assertEqual(self.admin_review(rejected, Entry.Status.REJECTED).status_code, 302)
        self.service_entry(tournament, player_id="NOW-HOLDS-THE-PLACE")
        response = self.admin_review(rejected, Entry.Status.APPROVED)
        self.assertEqual(response.status_code, 200)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Entry.Status.REJECTED)
        self.assertEqual(tournament.active_entry_count(), 1)

    def test_bulk_admin_reviews_create_audit_records_and_respect_restoration_capacity(self):
        tournament = self.make_tournament(capacity=2)
        entries = [self.service_entry(tournament, player_id=f"BULK-REVIEW-{number}") for number in (1, 2)]
        ids = [str(entry.pk) for entry in entries]
        self.client.force_login(self.owner)
        url = reverse("admin:arena_entry_changelist")

        def act(action):
            response = self.client.post(
                url, {"action": action, "_selected_action": ids, "index": "0", "select_across": "0"},
                secure=True,
            )
            self.assertEqual(response.status_code, 302)

        audit = LogEntry.objects.filter(
            user=self.owner, action_flag=CHANGE, object_id__in=ids,
            content_type__app_label="arena", content_type__model="entry",
        )
        act("approve_entries")
        self.assertEqual(Entry.objects.filter(status=Entry.Status.APPROVED).count(), 2)
        self.assertEqual(Entry.objects.filter(reviewed_by=self.owner, reviewed_at__isnull=False).count(), 2)
        self.assertEqual(audit.count(), 2)
        act("reject_entries")
        self.assertEqual(tournament.active_entry_count(), 0)
        self.assertEqual(audit.count(), 4)

        # A new entry takes one of the freed places. Bulk restoration may use
        # only the remaining place, even when both rejected rows are selected.
        self.service_entry(tournament, player_id="NEW-BULK-RESERVATION")
        act("approve_entries")
        self.assertEqual(tournament.active_entry_count(), 2)
        self.assertEqual(Entry.objects.filter(pk__in=ids, status=Entry.Status.APPROVED).count(), 1)
        self.assertEqual(Entry.objects.filter(pk__in=ids, status=Entry.Status.REJECTED).count(), 1)
        self.assertEqual(audit.count(), 5)

    def test_existing_entries_prevent_format_changes_and_reducing_capacity_below_reserved_places(self):
        tournament = self.make_tournament(capacity=2)
        self.service_entry(tournament, player_id="FIRST-RESERVATION")
        self.service_entry(tournament, player_id="SECOND-RESERVATION")
        for field, value in (("capacity", 1), ("team_size", 2), ("game", "valorant")):
            with self.subTest(field=field):
                tournament.refresh_from_db()
                setattr(tournament, field, value)
                with self.assertRaises(ValidationError):
                    tournament.full_clean()

    def test_csrf_is_enforced_and_a_valid_https_submission_works(self):
        client = Client(enforce_csrf_checks=True)
        tournament = self.make_tournament()
        data = self.registration_data(tournament, client=client)
        blocked = self.submit(tournament, data, client=client, HTTP_ORIGIN="https://testserver")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(Entry.objects.count(), 0)
        cookie = client.cookies[settings.CSRF_COOKIE_NAME]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        data["csrfmiddlewaretoken"] = cookie.value
        valid = self.submit(tournament, data, client=client, HTTP_ORIGIN="https://testserver")
        self.assertEqual(valid.status_code, 303)
        self.assertEqual(Entry.objects.count(), 1)

    def test_csrf_accepts_same_origin_referer_without_origin_and_keeps_receipts_private(self):
        client = Client(enforce_csrf_checks=True)
        tournament = self.make_tournament()
        url = reverse("arena:register", args=(tournament.pk,))
        page = client.get(url, secure=True)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.get("Referrer-Policy"), "same-origin")
        data = self.registration_data(tournament, client=client)
        data["csrfmiddlewaretoken"] = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.submit(
            tournament, data, client=client, HTTP_REFERER=f"https://testserver{url}",
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(Entry.objects.count(), 1)
        receipt = client.get(response["Location"], secure=True)
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.get("Referrer-Policy"), "no-referrer")
        self.assertIn("no-store", receipt.get("Cache-Control", ""))

    def test_http_redirects_to_https_while_the_trusted_proxy_header_works(self):
        response = self.client.get("/tournaments/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://testserver/tournaments/")
        proxied = self.client.get("/tournaments/", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(proxied.status_code, 200)

    def test_public_post_throttle_stops_repeated_attempts_without_creating_entries(self):
        tournament = self.make_tournament()
        data = self.registration_data(tournament)
        data["player_id"] = ""
        responses = []
        for _ in range(40):
            response = self.submit(tournament, data, REMOTE_ADDR="192.0.2.11")
            responses.append(response.status_code)
            if response.status_code == 429:
                break
        self.assertIn(429, responses)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertEqual(Entry.objects.count(), 0)
        self.assertEqual(self.client.get(tournament.get_absolute_url(), secure=True).status_code, 200)

    def test_admin_login_throttle_stops_repeated_failed_attempts(self):
        responses = []
        for _ in range(30):
            response = self.client.post(
                "/arena-admin/login/",
                {"username": "nonexistent-test-user", "password": "incorrect-test-password"},
                secure=True, REMOTE_ADDR="192.0.2.12",
            )
            responses.append(response.status_code)
            if response.status_code == 429:
                break
        self.assertIn(429, responses)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertNotIn("_auth_user_id", self.client.session)


class ConcurrentLastPlaceTests(TransactionTestCase):
    """Exercise SQLite's real file-lock behavior rather than its shared cache."""

    def test_two_simultaneous_entries_cannot_both_take_the_last_place(self):
        database_name = str(connection.settings_dict["NAME"])
        if connection.vendor != "sqlite" or database_name == ":memory:" or "mode=memory" in database_name:
            self.skipTest("Set CE_ARENA_TEST_DATABASE to an isolated file path for the SQLite concurrency check.")

        now = timezone.now()
        tournament = Tournament.objects.create(
            title="Concurrent last-place test", game="free-fire", status=Tournament.Status.OPEN,
            format_label="Solo test event", team_size=1, capacity=1,
            start_at=now + timedelta(days=2), registration_deadline=now + timedelta(days=1),
            rules="Fictional test rules.", entry_terms="Free test entry.",
        )
        revision = tournament_revision(tournament)
        barrier = Barrier(2, timeout=5)

        def compete_for_place(player_id):
            close_old_connections()
            try:
                # Both calls reach the service at once, before either enters
                # its IMMEDIATE transaction. Each uses its own connection.
                barrier.wait()
                entry = create_entry(
                    tournament.pk,
                    {"gaming_name": f"Test {player_id}", "player_id": player_id,
                     "team_name": "", "rules_accepted": True},
                    [], uuid.uuid4(), revision,
                )
                return "saved", entry.pk
            except RegistrationUnavailable:
                return "full", None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(compete_for_place, player) for player in ("RACE-A", "RACE-B")]
            outcomes = [future.result(timeout=25) for future in futures]

        self.assertCountEqual([status for status, _ in outcomes], ["saved", "full"])
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Entry.objects.get().status, Entry.Status.PENDING)
        self.assertEqual(Participant.objects.count(), 1)
        self.assertEqual(tournament.active_entry_count(), 1)
