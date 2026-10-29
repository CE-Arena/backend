from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from .forms import PlayerSignupForm
from arena.models import Entry
from .email_delivery import send_verification_email
from django.core.exceptions import ImproperlyConfigured
from smtplib import SMTPException
from .verification import InvalidVerificationToken, activate_verified_email


@never_cache
@sensitive_post_parameters("password1", "password2")
@csrf_protect
@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = PlayerSignupForm(
        request.POST if request.method == "POST" else None
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            form.add_error(
                None,
                "Account creation failed. Check your details and try again."
            )
        else:
            try:
                send_verification_email(user)
            except (
                ImproperlyConfigured,
                SMTPException,
                OSError,
                RuntimeError,
                InvalidVerificationToken,
            ):
                form.add_error(
                    None,
                    "Your account was created, but we could not "
                    "send the verification email. Your account "
                    "remains inactive. Please contact CE ARENA "
                    "support for assistance."
                )
            else:
                return redirect("accounts:check_email")

    return render(
        request,
        "accounts/signup.html",
        {"form": form}
    )


class PlayerLoginView(LoginView):
    template_name = "accounts/login.html"
    next_page = reverse_lazy("dashboard")
    redirect_authenticated_user = True


class PlayerLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")
    http_method_names = ["post", "options"]


@never_cache
@login_required(login_url="/accounts/login/")
@require_GET
def dashboard(request):
    entries = (
        Entry.objects.filter(registered_by=request.user)
        .select_related("tournament")
        .order_by("-created_at", "-pk")
    )

    return render(
        request,
        "accounts/dashboard.html",
        {
            "player": request.user,
            "entries": entries,
        },
    )



@never_cache
@require_GET
def email_confirmation(request, token):
    """Display confirmation without activating the account."""

    if len(token) > 1500:
        response = render(
            request,
            "accounts/verify_email.html",
            {"invalid": True},
            status=400,
        )
    else:
        response = render(
            request,
            "accounts/verify_email.html",
            {"token": token},
        )

    response["Referrer-Policy"] = "strict-origin"
    return response


@never_cache
@sensitive_post_parameters("token")
@csrf_protect
@require_http_methods(["POST"])
def verify_email(request):
    """Activate an account only after an explicit POST."""

    token = request.POST.get("token", "")

    try:
        activate_verified_email(token)
    except InvalidVerificationToken:
        response = render(
            request,
            "accounts/verify_email.html",
            {"invalid": True},
            status=400,
        )
        response["Referrer-Policy"] = "strict-origin"
        return response

    request.session["ce_arena_email_verified"] = True

    return redirect("accounts:verification_complete")


@never_cache
@require_GET
def verification_complete(request):
    """Show confirmation only after successful verification."""

    if not request.session.pop(
        "ce_arena_email_verified", False
    ):
        return redirect("accounts:login")

    return render(
        request,
        "accounts/verified.html",
    )



@never_cache
@require_GET
def check_email(request):
    return render(
        request,
        "accounts/check_email.html",
    )
