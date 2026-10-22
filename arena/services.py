"""All slot allocation happens within a short SQLite IMMEDIATE transaction."""
from django.db import IntegrityError, transaction

from .forms import tournament_revision
from .models import Entry, Participant, Tournament, normalize_player_id

class RegistrationUnavailable(Exception):
    pass

class DuplicatePlayer(Exception):
    pass

class InvalidSubmission(Exception):
    pass

def _same_submission(entry, cleaned_data, roster):
    expected = [(cleaned_data["gaming_name"], cleaned_data["player_id"])] + [(p["gaming_name"], p["player_id"]) for p in roster]
    actual = list(entry.participants.values_list("gaming_name", "player_id"))
    return entry.team_name == cleaned_data.get("team_name", "") and expected == actual

def create_entry(tournament_id, cleaned_data, roster, submission_key, expected_revision):
    try:
        with transaction.atomic():
            tournament = Tournament.objects.get(pk=tournament_id)
            existing = Entry.objects.filter(submission_key=submission_key).first()
            if existing:
                if existing.tournament_id == tournament_id and _same_submission(existing, cleaned_data, roster):
                    return existing
                raise InvalidSubmission("This form has already been used. Reload the page to start a new entry.")
            if not tournament.registration_is_open:
                raise RegistrationUnavailable("Registration for this tournament is closed.")
            if tournament_revision(tournament) != expected_revision:
                raise InvalidSubmission("The tournament details changed while you were filling in the form. Reload the page and review the updated details before entering.")
            if tournament.capacity is None or tournament.active_entry_count() >= tournament.capacity:
                raise RegistrationUnavailable("All available places have been reserved. Registration is currently full.")
            if not cleaned_data.get("rules_accepted"):
                raise InvalidSubmission("Read and accept the tournament rules and entry terms before entering.")
            if len(roster) != tournament.team_size - 1:
                raise InvalidSubmission("The team roster does not match the required number of players.")
            if tournament.team_size > 1 and not cleaned_data.get("team_name", "").strip():
                raise InvalidSubmission("Enter the team name.")
            players = [{"gaming_name": cleaned_data["gaming_name"], "player_id": cleaned_data["player_id"]}] + roster
            normalized_ids = [normalize_player_id(player["player_id"]) for player in players]
            if len(set(normalized_ids)) != len(normalized_ids):
                raise InvalidSubmission("Each player ID can appear only once in this entry.")
            if Participant.objects.filter(tournament=tournament, normalized_id__in=normalized_ids).exists():
                raise DuplicatePlayer("One or more player IDs already has an entry for this tournament. Check the saved receipt or ask CE ARENA to review the existing entry.")
            entry = Entry.objects.create(
                tournament=tournament, gaming_name=cleaned_data["gaming_name"], player_id=cleaned_data["player_id"],
                team_name=cleaned_data.get("team_name", "") if tournament.team_size > 1 else "",
                status=Entry.Status.PENDING, rules_snapshot=tournament.rules,
                entry_terms_snapshot=tournament.entry_terms, format_snapshot=tournament.format_label,
                submission_key=submission_key,
            )
            Participant.objects.bulk_create([
                Participant(entry=entry, tournament=tournament, position=index, gaming_name=player["gaming_name"],
                            player_id=player["player_id"], normalized_id=normalized_ids[index])
                for index, player in enumerate(players)
            ])
            return entry
    except IntegrityError as exc:
        # Uniqueness remains a database invariant even with concurrent requests.
        raise DuplicatePlayer("An entry already exists for one of these players or this form. Check your saved receipt before trying again.") from exc
