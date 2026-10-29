"""Production defaults. Read secrets and paths from ../config.json, never the webroot."""
import json
import ipaddress
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
TESTING = os.environ.get("CE_ARENA_TESTING") == "1"
CONFIG_PATH = Path(os.environ.get("CE_ARENA_CONFIG", str(BASE_DIR.parent / "config.json")))
if TESTING:
    CONFIG = {
        "secret_key": "test-only-key-for-isolated-ce-arena-tests-not-for-deployment-0123456789",
        "allowed_hosts": ["testserver", "localhost", "127.0.0.1"],
        "csrf_trusted_origins": ["https://testserver", "https://localhost"],
        "database_path": ":memory:",
        "static_root": str(BASE_DIR.parent / "test-static"),
        "secure_mode": True,
        "timezone": "Africa/Douala",
    }
else:
    try:
        CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImproperlyConfigured("Run the CE ARENA installer to create the private config.json.") from exc

SECRET_KEY = CONFIG["secret_key"]
if not isinstance(SECRET_KEY, str) or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("CE ARENA requires a randomly generated secret of at least 50 characters.")
DEBUG = False
ALLOWED_HOSTS = CONFIG["allowed_hosts"]
if not isinstance(ALLOWED_HOSTS, list) or not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set explicit allowed_hosts in config.json.")
CSRF_TRUSTED_ORIGINS = CONFIG["csrf_trusted_origins"]
if CONFIG.get("secure_mode") is not True:
    raise ImproperlyConfigured("Public registration and administration require HTTPS.")

INSTALLED_APPS = [
    "accounts.apps.AccountsConfig",
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "arena.apps.ArenaConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "arena.middleware.ResponsePrivacyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "arena.middleware.SubmissionLimitMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "arena_project.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages", "arena.context.common",
    ]},
}]
WSGI_APPLICATION = "arena_project.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": CONFIG["database_path"],
    "OPTIONS": {"timeout": 15, "transaction_mode": "IMMEDIATE"},
    "CONN_MAX_AGE": 0,
}}
if TESTING and os.environ.get("CE_ARENA_TEST_DATABASE"):
    DATABASES["default"]["TEST"] = {"NAME": os.environ["CE_ARENA_TEST_DATABASE"]}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = CONFIG.get("timezone", "Africa/Douala")
ZoneInfo(TIME_ZONE)  # Fail clearly if the configured time zone is invalid.
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/arena-assets/"
STATIC_ROOT = CONFIG["static_root"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if TESTING else "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

# Only Nginx, on the same host, can connect to the production loopback listener.
# Its proxy configuration overwrites this header rather than forwarding client input.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 86400
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# IP addresses have no subdomains and are not domain preload candidates.
# Do not enable these domain-wide policies merely to silence deployment checks.
try:
    ipaddress.ip_address(CONFIG.get("public_host", ""))
except ValueError:
    SILENCED_SYSTEM_CHECKS = []
else:
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_NAME = "ce_arena_session"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_NAME = "ce_arena_csrf"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
CSRF_FAILURE_VIEW = "arena.views.csrf_failure"
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 80
FILE_UPLOAD_MAX_MEMORY_SIZE = 0
LOGIN_URL = "/arena-admin/login/"

# No SMTP or third-party analytics are configured. Never log request bodies.
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}


# CE ARENA SMTP - EXPLICIT CONFIGURATION
# Credentials remain outside the Git repository.
# SMTP is enabled only when its credential path is supplied.

import os as _ce_mail_os
import json as _ce_mail_json

_ce_mail_path = _ce_mail_os.environ.get(
    "CE_ARENA_SMTP_CREDENTIALS"
)

if _ce_mail_path:
    with open(_ce_mail_path, encoding="utf-8") as _ce_mail_file:
        _ce_mail_credentials = _ce_mail_json.load(_ce_mail_file)

    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_USE_SSL = False
    EMAIL_TIMEOUT = 15

    EMAIL_HOST_USER = _ce_mail_credentials["email"]
    EMAIL_HOST_PASSWORD = _ce_mail_credentials["app_password"]

    DEFAULT_FROM_EMAIL = f"CE ARENA <{EMAIL_HOST_USER}>"

    del _ce_mail_credentials

# Set separately when a publicly reachable HTTPS endpoint is ready.
CE_ARENA_PUBLIC_ORIGIN = _ce_mail_os.environ.get(
    "CE_ARENA_PUBLIC_ORIGIN", ""
).strip().rstrip("/")
