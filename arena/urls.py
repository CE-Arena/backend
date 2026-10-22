from django.urls import path
from . import views

app_name = "arena"
urlpatterns = [
    path("", views.tournament_list, name="tournament_list"),
    path("health/", views.health, name="health"),
    path("privacy/", views.privacy, name="privacy"),
    path("game/<slug:game>/", views.game_tournaments, name="game_tournaments"),
    path("entry/<uuid:token>/", views.receipt, name="receipt"),
    path("<int:pk>/", views.tournament_detail, name="tournament_detail"),
    path("<int:pk>/rules/", views.tournament_section, {"section": "rules"}, name="tournament_rules"),
    path("<int:pk>/schedule/", views.tournament_section, {"section": "schedule"}, name="tournament_schedule"),
    path("<int:pk>/prizes/", views.tournament_section, {"section": "prizes"}, name="tournament_prizes"),
    path("<int:pk>/registration/", views.tournament_section, {"section": "registration"}, name="tournament_registration"),
    path("<int:pk>/register/", views.register, name="register"),
]
