import hashlib
import json
import unicodedata
import uuid

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.forms import formset_factory

from .models import normalize_player_id

FORM_SALT = "ce-arena-registration-v1"

def tournament_revision(tournament):
    values = [tournament.title, tournament.game, tournament.format_label, tournament.team_size,
              tournament.rules, tournament.entry_terms, tournament.prize_details,
              tournament.start_at.isoformat() if tournament.start_at else None,
              tournament.registration_deadline.isoformat() if tournament.registration_deadline else None]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()

def clean_text(value):
    value = unicodedata.normalize("NFKC", value).strip()
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValidationError("Enter text without hidden control characters.")
    return value

class NormalizedTextField(forms.CharField):
    def to_python(self, value):
        # Normalize before required/max_length validation: one Unicode character
        # can expand to several visible characters under NFKC normalization.
        return clean_text(super().to_python(value))

class PlayerForm(forms.Form):
    gaming_name = NormalizedTextField(label="Gaming name", max_length=60, strip=True,
                                 widget=forms.TextInput(attrs={"autocomplete": "off"}))
    player_id = NormalizedTextField(label="In-game player ID", max_length=80, strip=True,
                               help_text="Copy the ID exactly as it appears in the game. We do not ask for your game password.",
                               widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "none", "spellcheck": "false"}))

    def clean_gaming_name(self):
        return clean_text(self.cleaned_data["gaming_name"])

    def clean_player_id(self):
        return clean_text(self.cleaned_data["player_id"])

class RegistrationForm(PlayerForm):
    team_name = NormalizedTextField(max_length=80, required=False, widget=forms.TextInput(attrs={"autocomplete": "off"}))
    rules_accepted = forms.BooleanField(label="I have read and agree to this tournament’s published rules and entry terms.", required=True)
    website = forms.CharField(required=False, max_length=200,
                              widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}))
    submission_token = forms.CharField(widget=forms.HiddenInput, max_length=1500)

    def __init__(self, tournament, data=None, **kwargs):
        self.tournament = tournament
        super().__init__(data=data, **kwargs)
        if tournament.team_size > 1:
            self.fields["team_name"].required = True
            self.fields["gaming_name"].label = "Captain’s gaming name"
            self.fields["player_id"].label = "Captain’s in-game player ID"
            self.fields["team_name"].help_text = "Submit one entry for the whole team, with the captain listed first."
        else:
            self.fields.pop("team_name")
        if not self.is_bound:
            self.initial["submission_token"] = signing.dumps({
                "tournament": tournament.pk, "key": str(uuid.uuid4()), "revision": tournament_revision(tournament),
            }, salt=FORM_SALT, compress=True)

    def clean_team_name(self):
        return clean_text(self.cleaned_data.get("team_name", ""))

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise ValidationError("This entry could not be submitted. Reload the form and try again.")
        return ""

    def clean_submission_token(self):
        try:
            value = signing.loads(self.cleaned_data["submission_token"], salt=FORM_SALT, max_age=7200)
            if value["tournament"] != self.tournament.pk:
                raise ValueError("Wrong tournament")
            value["key"] = uuid.UUID(value["key"])
            if not isinstance(value["revision"], str) or len(value["revision"]) != 64:
                raise ValueError("Wrong revision")
        except (signing.BadSignature, KeyError, ValueError, TypeError):
            raise ValidationError("This form has expired or changed. Reload this page and enter your details again.")
        return value

def make_roster_formset(tournament, data=None):
    size = max(0, tournament.team_size - 1)
    RosterFormSet = formset_factory(PlayerForm, extra=size, min_num=0, max_num=size,
                                   validate_max=True, absolute_max=max(size, 1))
    formset = RosterFormSet(data=data, prefix="roster")
    # Every announced player position is required, including unchanged blank forms.
    for form in formset.forms:
        form.empty_permitted = False
    return formset

def validate_roster(tournament, form, formset):
    """Validate exact roster size, including tampered management fields."""
    valid_main = form.is_valid()
    valid_roster = formset.is_valid()
    if formset.total_form_count() != tournament.team_size - 1:
        form.add_error(None, "Enter exactly the number of teammates required for this tournament.")
        valid_roster = False
    if not (valid_main and valid_roster):
        return False
    players = [form.cleaned_data] + list(formset.cleaned_data)
    ids = [normalize_player_id(player["player_id"]) for player in players]
    if len(set(ids)) != len(ids):
        form.add_error(None, "Each player ID can appear only once in this team entry.")
        return False
    return True
