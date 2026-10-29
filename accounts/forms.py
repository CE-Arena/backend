from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction

from .models import PlayerEmail, normalize_player_email


class PlayerSignupForm(UserCreationForm):
    email = forms.EmailField(
        label="Email address",
        max_length=254,
        required=True,
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email", "password1", "password2")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        if get_user_model().objects.filter(
            username__iexact=username
        ).exists():
            raise forms.ValidationError(
                "This username is already taken."
            )

        return username

    def clean_email(self):
        email = normalize_player_email(self.cleaned_data["email"])
        email = self.fields["email"].clean(email)

        if (
            PlayerEmail.objects.filter(
                normalized_email=email
            ).exists()
            or get_user_model().objects.filter(
                email__iexact=email
            ).exists()
        ):
            raise forms.ValidationError(
                "This email address is already registered."
            )

        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]

        # New player accounts require verified email activation.
        user.is_active = False

        if commit:
            with transaction.atomic():
                user.save()
                PlayerEmail.objects.create(
                    user=user,
                    normalized_email=user.email,
                )

        return user
