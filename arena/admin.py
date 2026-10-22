from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Entry, Participant, Tournament

admin.site.site_header = "CE ARENA management"
admin.site.site_title = "CE ARENA"
admin.site.index_title = "Tournaments and registrations"
admin.site.site_url = "/tournaments/"

@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ("title", "game", "status", "start_at", "registration_deadline", "capacity", "entries_received")
    list_filter = ("status", "game")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Tournament", {"fields": ("title", "game", "status"), "description": "Drafts stay private. Fill in the real details, preview the page, then select Registration open when you are ready."}),
        ("Format and places", {"fields": ("format_label", "team_size", "capacity")}),
        ("Schedule — Africa/Douala", {"fields": ("start_at", "registration_deadline"), "description": "Enter Cameroon local time (UTC+1). Registration closes automatically at the deadline."}),
        ("Published information", {"fields": ("entry_terms", "prize_details", "rules"), "description": "Players accept the published rules and entry terms. Each entry keeps a copy of what that player accepted."}),
        ("Record", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Pending + approved")
    def entries_received(self, obj):
        return obj.active_entry_count()

    def view_on_site(self, obj):
        return reverse("arena_admin_preview", args=(obj.pk,))

class ParticipantInline(admin.TabularInline):
    model = Participant
    fields = ("position", "gaming_name", "player_id")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("reference", "tournament", "gaming_name", "team_name", "status", "created_at", "reviewed_by")
    list_filter = ("status", "tournament__game", "tournament")
    search_fields = ("gaming_name", "team_name", "player_id", "token", "participants__player_id")
    list_select_related = ("tournament", "reviewed_by")
    readonly_fields = ("reference", "tournament", "gaming_name", "player_id", "team_name", "rules_snapshot",
                       "entry_terms_snapshot", "format_snapshot", "created_at", "updated_at", "reviewed_at", "reviewed_by")
    fieldsets = (
        ("Review entry", {"fields": ("reference", "tournament", "status", "internal_note")}),
        ("Player or team", {"fields": ("gaming_name", "player_id", "team_name")}),
        ("Terms accepted at submission", {"fields": ("format_snapshot", "entry_terms_snapshot", "rules_snapshot"), "classes": ("collapse",)}),
        ("History", {"fields": ("created_at", "updated_at", "reviewed_at", "reviewed_by")}),
    )
    inlines = (ParticipantInline,)
    actions = ("approve_entries", "reject_entries")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)

    def set_status(self, request, queryset, status):
        changed = 0
        with transaction.atomic():
            for entry in queryset.select_related("tournament"):
                if entry.status == status:
                    continue
                entry.status = status
                try:
                    entry.full_clean()
                except ValidationError as exc:
                    self.message_user(request, f"{entry.reference}: {'; '.join(exc.messages)}", messages.ERROR)
                    continue
                entry.reviewed_by = request.user
                entry.reviewed_at = timezone.now()
                entry.save(update_fields=("status", "reviewed_by", "reviewed_at", "updated_at"))
                LogEntry.objects.log_actions(
                    user_id=request.user.pk, queryset=Entry.objects.filter(pk=entry.pk),
                    action_flag=CHANGE, change_message=f"Status changed to {entry.get_status_display()}.", single_object=True,
                )
                changed += 1
        self.message_user(request, f"Updated {changed} entr{'y' if changed == 1 else 'ies'}.", messages.SUCCESS)

    @admin.action(description="Approve selected entries", permissions=("change",))
    def approve_entries(self, request, queryset):
        self.set_status(request, queryset, Entry.Status.APPROVED)

    @admin.action(description="Reject selected entries", permissions=("change",))
    def reject_entries(self, request, queryset):
        self.set_status(request, queryset, Entry.Status.REJECTED)
