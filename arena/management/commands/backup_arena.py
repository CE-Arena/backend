"""Create a consistent SQLite snapshot outside the public website."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = "Back up the registration database to the backend's private backups directory."

    def handle(self, *args, **options):
        source = Path(settings.DATABASES["default"]["NAME"]).resolve()
        if not source.is_file():
            raise CommandError("The registration database does not exist.")
        destination_dir = source.parent.parent / "database-backups"
        if destination_dir.is_symlink():
            raise CommandError("Refusing a symlinked backup directory.")
        destination_dir.mkdir(mode=0o700, exist_ok=True)
        name = "arena-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3"
        destination = destination_dir / name
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        try:
            with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
                src.backup(dst)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise CommandError("The backup could not be completed.") from exc
        self.stdout.write(f"Database backup saved: {destination}")
