from django.urls import path
from . import views, resend

app_name = "accounts"

urlpatterns = [
    path("register/", views.signup, name="signup"),
    path("check-email/", views.check_email, name="check_email"),
    path("resend-verification/", resend.resend_verification, name="resend_verification"),
    path("login/", views.PlayerLoginView.as_view(), name="login"),
    path("logout/", views.PlayerLogoutView.as_view(), name="logout"),
    path("verify/confirm/", views.verify_email, name="verify_submit"),
    path("verify/complete/", views.verification_complete, name="verification_complete"),
    path("verify/<str:token>/", views.email_confirmation, name="verify_link"),
]
