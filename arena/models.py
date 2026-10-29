import unicodedata
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .constants import ACTIVE_ENTRY_STATUSES, GAMES

def normalize_player_id(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()

class Tournament(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft — private"
        OPEN = "open", "Registration open"
        CLOSED = "closed", "Registration closed"
        COMPLETED = "completed", "Completed"

    title = models.CharField(max_length=140)
    game = models.CharField(max_length=30, choices=GAMES, default="free-fire")
    status = models.CharField(max_length=12, choices=Status, default=Status.DRAFT)
    format_label = models.CharField("competition format", max_length=140, blank=True, help_text="Describe the actual mode and format before publishing.")
    team_size = models.PositiveSmallIntegerField("players per entry", default=1, validators=[MinValueValidator(1), MaxValueValidator(10)], help_text="1 for solo. For teams, include the captain. No substitute slots are collected.")
    capacity = models.PositiveIntegerField("entry capacity", blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(10000)], help_text="Number of players for solo, or teams for team events. Pending and approved entries both reserve a place.")
    start_at = models.DateTimeField("start date and time", blank=True, null=True)
    registration_deadline = models.DateTimeField(blank=True, null=True)
    rules = models.TextField(blank=True, max_length=15000, help_text="Include eligibility, game/platform, match format, fair play, scoring, attendance, disconnections and how participants get match details.")
    entry_terms = models.CharField("entry terms / fee", max_length=300, blank=True, help_text="State the confirmed entry conditions, for example 'Free entry'. This website does not collect payments.")
    prize_details = models.CharField(max_length=500, blank=True, help_text="Only confirmed prizes. Leave blank if none have been announced.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("start_at", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(team_size__gte=1, team_size__lte=10), name="tournament_team_size_1_10"),
            models.CheckConstraint(condition=models.Q(capacity__isnull=True) | models.Q(capacity__gte=1), name="tournament_capacity_positive"),
        ]

    def __str__(self):
        return self.title

    @property
    def game_label(self):
        return self.get_game_display()

    @property
    def entry_unit(self):
        return "teams" if self.team_size > 1 else "players"

    @property
    def registration_is_open(self):
        now = timezone.now()
        return bool(self.status == self.Status.OPEN and self.registration_deadline and self.start_at and now < self.registration_deadline and now < self.start_at)

    def active_entry_count(self):
        return self.entries.filter(status__in=ACTIVE_ENTRY_STATUSES).count()

    def get_absolute_url(self):
        return reverse("arena:tournament_detail", args=(self.pk,))

    def clean(self):
        errors = {}
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if self.status != self.Status.DRAFT:
            for field in ("format_label", "capacity", "start_at", "registration_deadline", "rules", "entry_terms"):
                if not getattr(self, field):
                    errors[field] = "Complete this field before publishing the tournament."
        if self.start_at and self.registration_deadline and self.registration_deadline > self.start_at:
            errors["registration_deadline"] = "Registration must close at or before the tournament starts."
        if self.status == self.Status.OPEN and (not previous or previous.status != self.Status.OPEN):
            if self.start_at and self.start_at <= timezone.now():
                errors["start_at"] = "Choose a future start time before opening registration."
            if self.registration_deadline and self.registration_deadline <= timezone.now():
                errors["registration_deadline"] = "Choose a future registration deadline before opening registration."
        if previous and previous.status != self.Status.DRAFT and self.status == self.Status.DRAFT:
            errors["status"] = "A published tournament cannot become a draft. Close registration instead."
        if previous and self.entries.exists():
            for field in ("game", "team_size"):
                if getattr(self, field) != getattr(previous, field):
                    errors[field] = "This cannot change after an entry has been received. Create a separate tournament for a different format."
            if self.capacity is not None and self.capacity < self.active_entry_count():
                errors["capacity"] = "Capacity cannot be lower than the number of pending and approved entries."
        if errors:
            raise ValidationError(errors)

    @property
    def spots_left(self):
        if self.capacity is None:
            return None
        return max(0, self.capacity - self.active_entry_count())

class Entry(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Not approved"

    tournament = models.ForeignKey(Tournament, on_delete=models.PROTECT, related_name="entries")
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="submitted_tournament_entries",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    gaming_name = models.CharField(max_length=60)
    player_id = models.CharField(max_length=80)
    team_name = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    rules_snapshot = models.TextField(editable=False)
    entry_terms_snapshot = models.TextField(editable=False)
    format_snapshot = models.CharField(max_length=140, editable=False)
    submission_key = models.UUIDField(unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_at = models.DateTimeField(blank=True, null=True, editable=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True, editable=False)
    internal_note = models.TextField(blank=True, max_length=2000, help_text="Private organizer note. Not shown on the player's receipt.")

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("tournament", "status"), name="entry_tournament_status")]

    def __str__(self):
        return f"{self.reference} — {self.team_name or self.gaming_name}"

    @property
    def reference(self):
        return "CE-" + self.token.hex.upper()

    def get_absolute_url(self):
        return reverse("arena:receipt", args=(self.token,))

    def clean(self):
        if self.pk and self.status in ACTIVE_ENTRY_STATUSES:
            previous = type(self).objects.get(pk=self.pk)
            if previous.status not in ACTIVE_ENTRY_STATUSES:
                tournament = self.tournament
                if tournament.capacity is not None and tournament.active_entry_count() >= tournament.capacity:
                    raise ValidationError({"status": "This tournament is full. A rejected entry cannot be restored until a place is available."})

class Participant(models.Model):
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="participants")
    tournament = models.ForeignKey(Tournament, on_delete=models.PROTECT)
    position = models.PositiveSmallIntegerField()
    gaming_name = models.CharField(max_length=60)
    player_id = models.CharField(max_length=80)
    normalized_id = models.CharField(max_length=240, editable=False)

    class Meta:
        ordering = ("position",)
        constraints = [
            models.UniqueConstraint(fields=("tournament", "normalized_id"), name="one_player_per_tournament"),
            models.UniqueConstraint(fields=("entry", "position"), name="one_player_per_position"),
        ]

    def __str__(self):
        return self.gaming_name

class SubmissionWindow(models.Model):
    """Short lived rate counters. The key is an HMAC, never a stored IP address."""
    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
