import unicodedata

from django.conf import settings
from django.db import models


def normalize_player_email(value):
    return unicodedata.normalize(
        "NFKC", value or ""
    ).strip().casefold()


class PlayerEmail(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="player_email_identity",
    )

    normalized_email = models.CharField(
        max_length=254,
        unique=True,
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def save(self, *args, **kwargs):
        self.normalized_email = normalize_player_email(
            self.normalized_email
        )

        if not self.normalized_email:
            raise ValueError("Player email cannot be empty.")

        return super().save(*args, **kwargs)

    def __str__(self):
        return self.normalized_email
