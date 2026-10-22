from django.conf import settings
from .constants import GAMES

def common(request):
    return {"games": GAMES, "timezone_label": settings.TIME_ZONE + " (UTC+1)" if settings.TIME_ZONE == "Africa/Douala" else settings.TIME_ZONE}
