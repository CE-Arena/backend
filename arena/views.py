from django.db import OperationalError, connection
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .constants import GAMES
from .forms import RegistrationForm, make_roster_formset, validate_roster
from .models import Entry, Tournament
from .services import DuplicatePlayer, InvalidSubmission, RegistrationUnavailable, create_entry

def published_tournaments():
    return Tournament.objects.exclude(status=Tournament.Status.DRAFT)

@require_GET
def tournament_list(request):
    return render(request, "arena/tournament_list.html", {"tournaments": published_tournaments(), "selected_game": None})

@require_GET
def game_tournaments(request, game):
    game_map = dict(GAMES)
    if game not in game_map:
        raise Http404
    return render(request, "arena/tournament_list.html", {"tournaments": published_tournaments().filter(game=game),
                  "selected_game": {"slug": game, "name": game_map[game]}})

def detail_context(tournament, **extra):
    count = tournament.active_entry_count()
    return {"tournament": tournament, "active_entry_count": count,
            "spots_left": max(0, (tournament.capacity or 0) - count), **extra}

@require_GET
def tournament_detail(request, pk):
    tournament = get_object_or_404(published_tournaments(), pk=pk)
    return render(request, "arena/tournament_detail.html", detail_context(tournament))

@require_GET
def admin_preview(request, pk):
    # Registered through admin.site.admin_view, with the model permission checked too.
    if not request.user.has_perm("arena.view_tournament"):
        return permission_denied(request)
    tournament = get_object_or_404(Tournament, pk=pk)
    return render(request, "arena/tournament_detail.html", detail_context(tournament, preview=True))

class SeeOther(HttpResponseRedirect):
    status_code = 303

@never_cache
@require_http_methods(["GET", "POST"])
def register(request, pk):
    tournament = get_object_or_404(published_tournaments(), pk=pk)
    if request.method == "GET" and (not tournament.registration_is_open or tournament.active_entry_count() >= (tournament.capacity or 0)):
        return unavailable(request, "Registration unavailable", "Registration is closed or all places are currently reserved.", tournament=tournament)
    form = RegistrationForm(tournament, request.POST if request.method == "POST" else None)
    roster = make_roster_formset(tournament, request.POST if request.method == "POST" else None)
    response_status = 200
    if request.method == "POST":
        if validate_roster(tournament, form, roster):
            token = form.cleaned_data["submission_token"]
            try:
                entry = create_entry(
                    tournament.pk,
                    form.cleaned_data,
                    list(roster.cleaned_data),
                    token["key"],
                    token["revision"],
                    registered_by=(
                        request.user
                        if request.user.is_authenticated
                        else None
                    ),
                )
            except (RegistrationUnavailable, DuplicatePlayer, InvalidSubmission) as exc:
                form.add_error(None, str(exc))
                response_status = 409
            except OperationalError:
                return unavailable(request, "Please try again shortly", "We could not confirm a saved entry because the service is busy. Reload the form and try again. If you have a receipt, check its status first.", status=503, tournament=tournament)
            else:
                return SeeOther(entry.get_absolute_url())
        else:
            response_status = 400
    return render(request, "arena/register.html", {"tournament": tournament, "form": form, "roster": roster}, status=response_status)

@never_cache
@require_GET
def receipt(request, token):
    entry = get_object_or_404(Entry.objects.select_related("tournament"), token=token)
    return render(request, "arena/receipt.html", {"entry": entry})

@require_GET
def privacy(request):
    return render(request, "arena/privacy.html")

@require_GET
def health(request):
    # Check database availability without exposing configuration or entry information.
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM arena_tournament LIMIT 1")
            cursor.fetchone()
    except OperationalError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})

def unavailable(request, title, message, *, status=200, tournament=None):
    return render(request, "arena/unavailable.html", {"title": title, "message": message, "tournament": tournament}, status=status)

def csrf_failure(request, reason=""):
    return unavailable(request, "Please refresh the form", "Your form session has expired or could not be verified. Reload the page before submitting again.", status=403)

def bad_request(request, exception=None):
    return unavailable(request, "This request could not be processed", "Open the tournament page and try again.", status=400)

def permission_denied(request, exception=None):
    return unavailable(request, "Access restricted", "You do not have permission to open this page.", status=403)

def not_found(request, exception=None):
    return render(request, "arena/404.html", status=404)

def server_error(request):
    # Keep the error response independent of storage, database and template availability.
    return HttpResponse("CE ARENA is temporarily unavailable. Please try again shortly. If you already received an entry receipt, keep that link.", status=500, content_type="text/plain; charset=utf-8")


# CE ARENA: Dedicated read-only tournament information pages.
@require_GET
def tournament_section(request, pk, section):
    if section not in {"rules", "schedule", "prizes", "registration"}:
        from django.http import Http404
        raise Http404("Unknown tournament section")
    # Use the same published-only queryset and context as tournament_detail.
    tournament = get_object_or_404(published_tournaments(), pk=pk)
    context = detail_context(tournament)
    context["section"] = section
    return render(request, "arena/tournament_section.html", context)
