from django.core.management.base import BaseCommand
from arena.models import Tournament

class Command(BaseCommand):
    help = "Create the first private Free Fire draft only when no tournaments exist."

    def handle(self, *args, **options):
        if Tournament.objects.exists():
            self.stdout.write("Existing tournaments preserved; no sample event was created.")
            return
        Tournament.objects.create(title="Free Fire — draft tournament", game="free-fire", status="draft")
        self.stdout.write("Created one private Free Fire draft. No dates, fees, prizes or registration have been published.")
