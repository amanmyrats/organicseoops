import os
import base64
import hashlib
import re
import ssl
import ipaddress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from cryptography.fernet import Fernet
from kombu import Queue

from .artifacts import artifact_settings

BASE_DIR = Path(__file__).resolve().parent.parent

# Direct host commands use the local file; Compose already supplies every required
# value and production explicitly supplies its own environment.
def load_local_env(path=BASE_DIR / ".env"):
    if (
        os.environ.get("DJANGO_ENV") == "production"
        or os.environ.get("DJANGO_DEBUG") == "0"
        or all(key in os.environ for key in ("DJANGO_SECRET_KEY", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_HOST"))
        or not path.is_file()
    ):
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator and key.isidentifier():
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


load_local_env()

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = list(filter(None, os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.headless",
    "allauth.mfa",
    "allauth.usersessions",
    "rest_framework",
    "accounts",
    "tenancy",
    "jobs",
    "providers",
    "integrations",
]
MIDDLEWARE = [
    "config.observability.RequestIdMiddleware",
    "tenancy.public_analytics_api.PublicAnalyticsRequestGuard",
    "tenancy.public_contact_api.PublicContactRequestGuard",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "jobs.bot_log_upload.BotLogBodyGuard",
    "integrations.yandex_upload.YandexBodyGuard",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "allauth.usersessions.middleware.UserSessionsMiddleware",
    "accounts.middleware.StaffMFAMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Require an explicit target so a missing variable cannot select a host database.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "OPTIONS": {"connect_timeout": 5},
    },
}
_postgres_sslmode = os.environ.get("POSTGRES_SSLMODE", "")
_postgres_sslrootcert = os.environ.get("POSTGRES_SSLROOTCERT", "")
if _postgres_sslmode or _postgres_sslrootcert:
    if (_postgres_sslmode != "verify-full" or not _postgres_sslrootcert.startswith("/")
        or "\n" in _postgres_sslrootcert):
        raise ImproperlyConfigured("PostgreSQL TLS requires verify-full and an absolute CA path")
    DATABASES["default"]["OPTIONS"].update(sslmode=_postgres_sslmode, sslrootcert=_postgres_sslrootcert)
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.auth.EmailAuthenticationBackend"]
ACCOUNT_ADAPTER = "accounts.auth.AccountAdapter"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:8080").rstrip("/")
if os.environ.get("PUBLIC_ANALYTICS_ENABLED", "0") not in {"0", "1"}:
    raise ImproperlyConfigured("PUBLIC_ANALYTICS_ENABLED must be 0 or 1")
PUBLIC_ANALYTICS_ENABLED = os.environ.get("PUBLIC_ANALYTICS_ENABLED", "0") == "1"
PUBLIC_ANALYTICS_POLICY_FILE = os.environ.get("PUBLIC_ANALYTICS_POLICY_FILE", "")
PUBLIC_ANALYTICS_POLICY_SHA256 = os.environ.get("PUBLIC_ANALYTICS_POLICY_SHA256", "")
if os.environ.get("PUBLIC_CONTACT_ENABLED", "0") not in {"0", "1"}:
    raise ImproperlyConfigured("PUBLIC_CONTACT_ENABLED must be 0 or 1")
PUBLIC_CONTACT_ENABLED = os.environ.get("PUBLIC_CONTACT_ENABLED", "0") == "1"
_contact_retention = os.environ.get("PUBLIC_CONTACT_RETENTION_DAYS", "")
if _contact_retention and (not _contact_retention.isascii() or not _contact_retention.isdecimal()
                           or len(_contact_retention) > 3 or not 1 <= int(_contact_retention) <= 365):
    raise ImproperlyConfigured("PUBLIC_CONTACT_RETENTION_DAYS requires reviewed days from 1 to 365")
PUBLIC_CONTACT_RETENTION_DAYS = int(_contact_retention) if _contact_retention else None
_frontend_url = urlsplit(FRONTEND_ORIGIN)
if (
    _frontend_url.scheme not in {"http", "https"}
    or not _frontend_url.hostname
    or _frontend_url.username
    or _frontend_url.password
    or _frontend_url.path
    or _frontend_url.query
    or _frontend_url.fragment
    or (_frontend_url.scheme != "https" and _frontend_url.hostname not in {"localhost", "127.0.0.1"})
):
    raise ImproperlyConfigured("FRONTEND_ORIGIN must be an HTTPS origin, or HTTP localhost for development")
HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("browser",)
LOGIN_URL = f"{FRONTEND_ORIGIN}/account/login"
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": f"{FRONTEND_ORIGIN}/account/verify-email#{{key}}",
    "account_reset_password": f"{FRONTEND_ORIGIN}/account/forgot-password",
    "account_reset_password_from_key": f"{FRONTEND_ORIGIN}/account/reset-password#{{key}}",
    "account_signup": f"{FRONTEND_ORIGIN}/account/register",
}
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_DISPLAY = "accounts.models.user_display"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_EMAIL_CONFIRMATION_HMAC = False
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_SESSION_REMEMBER = False
ACCOUNT_CHANGE_EMAIL = True
ACCOUNT_REAUTHENTICATION_REQUIRED = True
ACCOUNT_REAUTHENTICATION_TIMEOUT = 300
ACCOUNT_EMAIL_NOTIFICATIONS = True
ACCOUNT_LOGIN_ON_PASSWORD_RESET = False
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
PASSWORD_RESET_TIMEOUT = 3600
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[OrganicSEOOps] "
MFA_ADAPTER = "accounts.auth.StaffMFAAdapter"
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_RECOVERY_CODES_SHOW_ONCE = True
MFA_TOTP_ISSUER = "OrganicSEOOps"
MFA_TRUST_ENABLED = False
_mfa_encryption_keys = tuple(filter(None, os.environ.get("MFA_ENCRYPTION_KEYS", "").split(",")))
if not _mfa_encryption_keys:
    if not DEBUG:
        raise ImproperlyConfigured("MFA_ENCRYPTION_KEYS is required outside development")
    _mfa_encryption_keys = (
        base64.urlsafe_b64encode(hashlib.sha256(f"{SECRET_KEY}:staff-mfa".encode()).digest()).decode(),
    )
try:
    for _mfa_encryption_key in _mfa_encryption_keys:
        Fernet(_mfa_encryption_key.encode())
except (TypeError, ValueError) as error:
    raise ImproperlyConfigured("MFA_ENCRYPTION_KEYS must contain comma-separated Fernet keys") from error
MFA_ENCRYPTION_KEYS = _mfa_encryption_keys
YANDEX_OAUTH_ENCRYPTION_KEYS = tuple(filter(None, os.environ.get("YANDEX_OAUTH_ENCRYPTION_KEYS", "").split(",")))
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")
GOOGLE_OAUTH_ENCRYPTION_KEYS = tuple(filter(None, os.environ.get("GOOGLE_OAUTH_ENCRYPTION_KEYS", "").split(",")))
GOOGLE_ANALYTICS_REDIRECT_URI = os.environ.get("GOOGLE_ANALYTICS_REDIRECT_URI", "")
GOOGLE_ANALYTICS_ENCRYPTION_KEYS = tuple(filter(None, os.environ.get("GOOGLE_ANALYTICS_ENCRYPTION_KEYS", "").split(",")))
PADDLE_ENCRYPTION_KEYS = tuple(filter(None, os.environ.get("PADDLE_ENCRYPTION_KEYS", "").split(",")))
PADDLE_ENVIRONMENT = os.environ.get("PADDLE_ENVIRONMENT", "")
if PADDLE_ENVIRONMENT not in {"", "sandbox", "live"}:
    raise ImproperlyConfigured("PADDLE_ENVIRONMENT must be sandbox or live when configured")
PADDLE_CHECKOUT_URL = os.environ.get("PADDLE_CHECKOUT_URL", "")
if PADDLE_CHECKOUT_URL:
    from urllib.parse import urlsplit as _split_checkout_url
    _checkout_parts = _split_checkout_url(PADDLE_CHECKOUT_URL)
    _frontend_parts = _split_checkout_url(FRONTEND_ORIGIN)
    if (_checkout_parts.scheme != "https" or _checkout_parts.netloc != _frontend_parts.netloc
        or not _checkout_parts.path.startswith("/account/") or _checkout_parts.username
        or _checkout_parts.password or _checkout_parts.query or _checkout_parts.fragment):
        raise ImproperlyConfigured("PADDLE_CHECKOUT_URL must be an HTTPS account route on FRONTEND_ORIGIN")
try:
    for _paddle_key in PADDLE_ENCRYPTION_KEYS:
        Fernet(_paddle_key.encode())
except (TypeError, ValueError) as error:
    raise ImproperlyConfigured("PADDLE_ENCRYPTION_KEYS must contain valid Fernet keys") from error
GOOGLE_PERFORMANCE_API_KEY = os.environ.get("GOOGLE_PERFORMANCE_API_KEY", "")
PERFORMANCE_ENCRYPTION_KEYS = tuple(filter(None, os.environ.get("PERFORMANCE_ENCRYPTION_KEYS", "").split(",")))
try:
    for _performance_key in PERFORMANCE_ENCRYPTION_KEYS:
        Fernet(_performance_key.encode())
except (TypeError, ValueError) as error:
    raise ImproperlyConfigured("PERFORMANCE_ENCRYPTION_KEYS must contain valid Fernet keys") from error
PROVIDER_ENCRYPTION_KEYS = tuple(filter(None, os.environ.get("PROVIDER_ENCRYPTION_KEYS", "").split(",")))
try:
    for _provider_encryption_key in PROVIDER_ENCRYPTION_KEYS:
        Fernet(_provider_encryption_key.encode())
except (TypeError, ValueError) as error:
    raise ImproperlyConfigured("PROVIDER_ENCRYPTION_KEYS must contain valid Fernet keys") from error
if any((GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI)) and not all(
        (GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI, GOOGLE_OAUTH_ENCRYPTION_KEYS)):
    raise ImproperlyConfigured("Google OAuth requires a client ID, secret, exact redirect URI and encryption keys together")
try:
    for _google_oauth_key in GOOGLE_OAUTH_ENCRYPTION_KEYS:
        Fernet(_google_oauth_key.encode())
except (TypeError, ValueError) as error:
    raise ImproperlyConfigured("GOOGLE_OAUTH_ENCRYPTION_KEYS must contain valid Fernet keys") from error
if GOOGLE_ANALYTICS_REDIRECT_URI and not GOOGLE_ANALYTICS_ENCRYPTION_KEYS:
    raise ImproperlyConfigured("Google Analytics OAuth requires independent encryption keys")
try:
    for _ga4_key in GOOGLE_ANALYTICS_ENCRYPTION_KEYS:
        Fernet(_ga4_key.encode())
except (TypeError, ValueError) as error:
    raise ImproperlyConfigured("GOOGLE_ANALYTICS_ENCRYPTION_KEYS must contain valid Fernet keys") from error
AI_PROVIDER_SECRET_REFERENCES = frozenset({"env:OPENAI_API_KEY", "env:OPENAI_COMPATIBLE_API_KEY"})
STAFF_MFA_REQUIRED = not DEBUG
if os.environ.get("SELF_SERVICE_CLOSURE_ENABLED", "0") not in {"0", "1"}:
    raise ImproperlyConfigured("SELF_SERVICE_CLOSURE_ENABLED must be 0 or 1")
SELF_SERVICE_CLOSURE_ENABLED = os.environ.get("SELF_SERVICE_CLOSURE_ENABLED", "0") == "1"
if os.environ.get("SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED", "0") not in {"0", "1"}:
    raise ImproperlyConfigured("SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED must be 0 or 1")
SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED = os.environ.get("SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED", "0") == "1"
# Absence keeps the independent staff identity cleanup unavailable; no retention period is selected here.
# Unset policy preserves existing captures; reviewed values apply only at READY publication.
CUSTOMER_EXPORT_COPY_POLICY_REFERENCE = os.environ.get("CUSTOMER_EXPORT_COPY_POLICY_REFERENCE", "")
try:
    CUSTOMER_EXPORT_COPY_LIFETIME_DAYS = int(os.environ.get("CUSTOMER_EXPORT_COPY_LIFETIME_DAYS") or "0")
except ValueError as exc:
    raise ImproperlyConfigured("CUSTOMER_EXPORT_COPY_LIFETIME_DAYS must be an integer") from exc

PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE = os.environ.get("PERSONAL_IDENTITY_ERASURE_POLICY_REFERENCE", "")
PERSONAL_IDENTITY_RETENTION_KEY = os.environ.get("PERSONAL_IDENTITY_RETENTION_KEY", "")
try:
    PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS = int(os.environ.get("PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS") or "0")
except ValueError as exc:
    raise ImproperlyConfigured("PERSONAL_IDENTITY_TRIAL_RETENTION_DAYS must be an integer") from exc
ORGANIZATION_INVITATION_EXPIRE_DAYS = 7
ACCOUNT_RATE_LIMITS = {
    "signup": "20/m/ip",
    "login": "30/m/ip",
    "login_failed": "10/m/ip,5/5m/key",
    "confirm_email": "1/3m/key,5/h/ip",
    "change_password": "5/m/user",
    "account_export": "3/h/user,10/h/ip",
    "account_close": "3/h/user,10/h/ip",
    "staff_identity_cleanup": "3/h/user,10/h/ip",
    "manage_email": "10/m/user",
    "reset_password": "20/m/ip,5/m/key",
    "reset_password_from_key": "20/m/ip",
    "reauthenticate": "10/m/user",
    "logout_all": "5/m/user",
    "invite_member": "10/h/user,3/h/key,30/h/ip",
    "invitation_accept": "20/m/user,30/m/ip",
    "manage_team": "20/m/user,60/m/ip",
    "platform_suspension": "10/h/user,30/h/ip",
    "platform_trial": "10/h/user,30/h/ip",
    "staff_trial_access": "60/m/user,120/m/ip",
    "staff_subscription_access": "60/m/user,120/m/ip",
    "staff_subscription_history_access": "60/m/user,120/m/ip",
    "staff_cancellation_access": "60/m/user,120/m/ip",
    "staff_checkout_access": "60/m/user,120/m/ip",
    "staff_checkout_link_access": "60/m/user,120/m/ip",
    "staff_first_active_access": "60/m/user,120/m/ip",
    "platform_provider_secret": "5/h/user,20/h/ip",
    "billing_checkout": "3/h/user,10/h/ip",
    "billing_checkout_receipt_read": "60/m/user,120/m/ip",
    "billing_checkout_receipt": "20/h/user,60/h/ip",
    "billing_portal": "5/h/user,20/h/ip",
    "organization_provider_secret": "10/h/user,40/h/ip",
    "origin_verification": "10/h/user,30/h/ip",
    "competitor_page_destinations_read": "60/m/user,120/m/ip",
    "competitor_lighthouse_read": "60/m/user,120/m/ip",
    "competitor_lighthouse_selection": "30/h/user,60/h/ip",
    "competitor_lighthouse_request": "10/h/user,30/h/ip",
    "competitor_lighthouse_cancel": "30/h/user,60/h/ip",
    "competitor_page_formats_read": "60/m/user,120/m/ip",
    "competitor_page_formats_selection": "30/h/user,60/h/ip",
    "competitor_page_formats_request": "10/h/user,30/h/ip",
    "competitor_page_formats_cancel": "30/h/user,60/h/ip",
    "competitor_page_dates_read": "60/m/user,120/m/ip",
    "competitor_page_dates_selection": "30/h/user,60/h/ip",
    "competitor_page_dates_request": "10/h/user,30/h/ip",
    "competitor_page_dates_cancel": "30/h/user,60/h/ip",
    "competitor_page_headings_read": "60/m/user,120/m/ip",
    "competitor_page_destinations_selection": "30/h/user,60/h/ip",
    "competitor_page_headings_selection": "30/h/user,60/h/ip",
    "competitor_page_destinations_request": "10/h/user,30/h/ip",
    "competitor_page_headings_request": "10/h/user,30/h/ip",
    "competitor_page_destinations_cancel": "30/h/user,60/h/ip",
    "competitor_page_headings_cancel": "30/h/user,60/h/ip",
    "competitor_page_read": "60/m/user,120/m/ip",
    "competitor_page_selection": "30/h/user,60/h/ip",
    "competitor_page_request": "10/h/user,30/h/ip",
    "competitor_page_cancel": "30/h/user,60/h/ip",
    "competitor_links_root_read": "60/m/user,120/m/ip",
    "competitor_links_root_selection": "30/h/user,60/h/ip",
    "competitor_links_root_request": "10/h/user,30/h/ip",
    "competitor_links_root_cancel": "30/h/user,60/h/ip",
    "competitor_schema_root_read": "60/m/user,120/m/ip",
    "competitor_schema_root_selection": "30/h/user,60/h/ip",
    "competitor_schema_root_request": "10/h/user,30/h/ip",
    "competitor_schema_root_cancel": "30/h/user,60/h/ip",
    "competitor_root_read": "60/m/user,120/m/ip",
    "competitor_root_selection": "30/h/user,60/h/ip",
    "competitor_root_request": "10/h/user,30/h/ip",
    "competitor_root_cancel": "30/h/user,60/h/ip",
    "competitor_heading_topics_read": "60/m/user,120/m/ip",
    "competitor_heading_topics_selection": "30/h/user,60/h/ip",
    "competitor_heading_topics_request": "10/h/user,30/h/ip",
    "competitor_heading_topics_cancel": "30/h/user,60/h/ip",
    "competitor_heading_synthesis_read": "60/m/user,120/m/ip",
    "competitor_heading_synthesis_selection": "30/h/user,60/h/ip",
    "competitor_heading_synthesis_request": "10/h/user,30/h/ip",
    "competitor_heading_synthesis_cancel": "30/h/user,60/h/ip",
    "competitor_synthesis_read": "60/m/user,120/m/ip",
    "competitor_synthesis_selection": "30/h/user,60/h/ip",
    "competitor_synthesis_request": "10/h/user,30/h/ip",
    "competitor_synthesis_cancel": "30/h/user,60/h/ip",
    "passive_header_read": "60/m/user,120/m/ip",
    "passive_header_findings_read": "60/m/user,120/m/ip",
    "passive_header_findings_write": "20/h/user,60/h/ip",
    "passive_header_priority_read": "60/m/user,120/m/ip",
    "passive_header_priority_write": "20/h/user,60/h/ip",
    "passive_header_selection": "30/m/user,60/m/ip",
    "passive_header_request": "10/h/user,30/h/ip",
    "passive_header_cancel": "30/h/user,60/h/ip",
    "passive_tls_read": "60/m/user,120/m/ip",
    "passive_tls_findings_read": "60/m/user,120/m/ip",
    "passive_tls_findings_write": "20/h/user,60/h/ip",
    "passive_tls_priority_read": "60/m/user,120/m/ip",
    "passive_tls_priority_write": "20/h/user,60/h/ip",
    "passive_tls_selection": "30/m/user,60/m/ip",
    "passive_tls_request": "10/h/user,30/h/ip",
    "passive_tls_cancel": "30/h/user,60/h/ip",
    "passive_resource_read": "60/m/user,120/m/ip",
    "passive_resource_findings_read": "60/m/user,120/m/ip",
    "passive_resource_findings_write": "20/h/user,60/h/ip",
    "passive_resource_priority_read": "60/m/user,120/m/ip",
    "passive_resource_priority_write": "20/h/user,60/h/ip",
    "passive_resource_selection": "30/m/user,60/m/ip",
    "passive_resource_request": "10/h/user,30/h/ip",
    "passive_resource_cancel": "30/h/user,60/h/ip",
    "passive_redirect_read": "60/m/user,120/m/ip",
    "passive_redirect_findings_read": "60/m/user,120/m/ip",
    "passive_redirect_findings_write": "20/h/user,60/h/ip",
    "passive_redirect_priority_read": "60/m/user,120/m/ip",
    "passive_redirect_priority_write": "20/h/user,60/h/ip",
    "passive_redirect_chain_priority_read": "60/m/user,120/m/ip",
    "passive_redirect_chain_priority_write": "20/h/user,60/h/ip",
    "passive_redirect_selection": "30/m/user,60/m/ip",
    "passive_redirect_request": "10/h/user,30/h/ip",
    "passive_redirect_cancel": "30/h/user,60/h/ip",
    "passive_http_redirect_read": "60/m/user,120/m/ip",
    "passive_http_redirect_selection": "30/m/user,60/m/ip",
    "passive_http_redirect_request": "10/h/user,30/h/ip",
    "passive_http_redirect_cancel": "30/h/user,60/h/ip",
    "passive_redirect_chain_read": "60/m/user,120/m/ip",
    "passive_redirect_chain_findings_read": "60/m/user,120/m/ip",
    "passive_redirect_chain_findings_write": "20/h/user,60/h/ip",
    "passive_redirect_chain_selection": "30/m/user,60/m/ip",
    "passive_redirect_chain_request": "10/h/user,30/h/ip",
    "passive_redirect_chain_cancel": "30/h/user,60/h/ip",
    "bot_log_import": "10/h/user,30/h/ip",
    "yandex_csv_import": "10/h/user,30/h/ip",
    "yandex_sync": "10/h/user,30/h/ip",
    "serp_observation": "10/h/user,30/h/ip",
    "repository_consent": "10/h/user,30/h/ip",
    "repository_analysis": "10/h/user,30/h/ip",
    "repository_callback": "30/h/user,60/h/ip",
    "yandex_oauth_start": "5/h/user,20/h/ip",
    "yandex_oauth_callback": "30/h/user,60/h/ip",
    "yandex_oauth_revoke": "10/h/user,30/h/ip",
    "csv_source_create": "20/h/user,40/h/ip",
    "search_console_csv_upload": "10/h/user,30/h/ip",
    "google_oauth_start": "5/h/user,20/h/ip",
    "google_oauth_callback": "30/h/user,60/h/ip",
    "business_profile_request": "20/h/user,40/h/ip",
    "ga4_oauth_manage": "20/h/user,40/h/ip",
    "ga4_sync": "3/h/user,10/h/ip",
    "search_console_sync": "3/h/user,10/h/ip",
    "search_console_coverage": "3/h/user,10/h/ip",
    "performance_audit": "3/h/user,10/h/ip",
    "first_audit_history_read": "30/m/user,60/m/ip",
    "first_audit_usefulness_ack": "20/h/user,60/h/ip",
    "public_contact_csrf": "30/m/ip",
    "public_contact_create": "10/h/ip",
    "public_contact_receipt": "60/m/ip",
    "public_contact_staff": "30/m/user,60/m/ip",
    "public_analytics_csrf": "30/m/ip",
    "public_analytics_grant": "10/h/ip",
    "public_analytics_receipt": "60/m/ip",
    "public_analytics_withdraw": "60/m/ip",
    "public_analytics_staff_read": "30/m/user,60/m/ip",
    "trial_paid_cohort_read": "5/m/user,10/m/ip",
    "finding_materialize": "10/h/user,30/h/ip",
    "intent_review": "20/h/user,60/h/ip",
    "action_review": "20/h/user,60/h/ip",
    "outcome_review": "10/h/user,30/h/ip",
    "local_review": "10/h/user,30/h/ip",
    "local_feedback_review": "30/h/user,60/h/ip",
    "authority_prospect_review": "30/h/user,60/h/ip",
    "content_lifecycle_review": "30/h/user,60/h/ip",
    "authority_link_review": "30/h/user,60/h/ip",
    "authority_source_request": "10/h/user,30/h/ip",
    "authority_source_cancel": "30/h/user,60/h/ip",
    "local_visibility_review": "30/h/user,60/h/ip",
    "visibility_manual_review": "30/h/user,60/h/ip",
    "report_export": "5/h/user,20/h/ip",
    "summary_preference_read": "60/m/user,120/m/ip",
    "alert_preference_read": "60/m/user,120/m/ip",
    "alert_preference_write": "30/m/user,60/m/ip",
    "summary_history_read": "60/m/user,120/m/ip",
    "crawl_failure_read": "60/m/user,120/m/ip",
    "integration_health_read": "60/m/user,120/m/ip",
    "alert_history_read": "60/m/user,120/m/ip",
    "crux_history_source_read": "60/m/user,120/m/ip",
    "crux_threshold_policy_read": "60/m/user,120/m/ip",
    "crux_preference_read": "60/m/user,120/m/ip",
    "crux_preference_write": "30/m/user,60/m/ip",
    "crux_delivery_history_read": "60/m/user,120/m/ip",
    "support_job_reference_read": "60/m/user,120/m/ip",
    "support_request_read": "60/m/user,120/m/ip",
    "support_request_create": "10/h/user,30/h/ip",
    "support_staff_access": "60/m/user,120/m/ip",
    "staff_job_access": "60/m/user,120/m/ip",
    "staff_usage_access": "60/m/user,120/m/ip",
    "staff_ai_usage_access": "60/m/user,120/m/ip",
    "staff_notice_access": "60/m/user,120/m/ip",
    "staff_account_mail_access": "60/m/user,120/m/ip",
    "staff_email_feedback_access": "60/m/user,120/m/ip",
    "staff_billing_receipt_access": "60/m/user,120/m/ip",
    "support_staff_update": "30/m/user,60/m/ip",
    "summary_preference_write": "30/m/user,60/m/ip",
    "report_share_create": "10/h/user,20/h/ip",
    "report_share_revoke": "60/m/user,120/m/ip",
    "report_share_read": "30/m/ip",
    "organization_report_bundle": "5/h/user,20/h/ip",
    "organization_export_inventory": "20/h/user,60/h/ip",
    "organization_export_rows": "200/h/user,400/h/ip",
    "organization_export_artifact": "100/h/user,200/h/ip",
    "organization_export_archive": "3/h/user,6/h/ip",
    "organization_export_snapshot": "3/h/user,6/h/ip",
    "organization_export_snapshot_read": "100/h/user,200/h/ip",
    "organization_export_snapshot_discard": "10/h/user,20/h/ip",
    "organization_closure_status": "20/h/user,60/h/ip",
    "organization_close": "3/h/user,10/h/ip",
    "organization_closure_reconcile": "5/h/user,20/h/ip",
    "organization_closure_revoke": "50/h/user,100/h/ip",
    "ai_text_request": "10/h/user,30/h/ip",
}
ALLAUTH_TRUSTED_PROXY_COUNT = 1

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("DJANGO_CACHE_URL", "redis://redis:6379/1"),
    },
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_SSL_REDIRECT = not DEBUG
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_artifact_storage, ARTIFACT_MAX_BYTES, ARTIFACT_ALLOWED_CONTENT_TYPES = artifact_settings(
    os.environ, default_local_root=BASE_DIR / "private-artifacts",
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "artifacts": _artifact_storage,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_ALLOW_ALL_ORIGINS = False
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND") or (
    "django.core.mail.backends.console.EmailBackend" if DEBUG else ""
)
EMAIL_DELIVERY_ENABLED = os.environ.get("EMAIL_DELIVERY_ENABLED", "1")
if EMAIL_DELIVERY_ENABLED not in {"0", "1"}:
    raise ImproperlyConfigured("EMAIL_DELIVERY_ENABLED must be 0 or 1")
EMAIL_DELIVERY_ENABLED = EMAIL_DELIVERY_ENABLED == "1"
if (not EMAIL_BACKEND or (not DEBUG and EMAIL_DELIVERY_ENABLED
        and EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend")):
    raise ImproperlyConfigured("EMAIL_BACKEND must use a delivery backend outside development")
if not EMAIL_DELIVERY_ENABLED and EMAIL_BACKEND != "django.core.mail.backends.dummy.EmailBackend":
    raise ImproperlyConfigured("Non-mail processes must disable delivery with the dummy backend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "")
SES_FEEDBACK_QUEUE_URL = os.environ.get("SES_FEEDBACK_QUEUE_URL", "")
SES_FEEDBACK_TOPIC_ARN = os.environ.get("SES_FEEDBACK_TOPIC_ARN", "")
SES_FEEDBACK_REGION = os.environ.get("AWS_REGION", "")
FEEDBACK_WORKER_HOST = os.environ.get("FEEDBACK_WORKER_HOST", "0")
if FEEDBACK_WORKER_HOST not in {"0", "1"}:
    raise ImproperlyConfigured("FEEDBACK_WORKER_HOST must be 0 or 1")
FEEDBACK_WORKER_HOST = FEEDBACK_WORKER_HOST == "1"
PRODUCTION_APP_HOST = os.environ.get("PRODUCTION_APP_HOST", "0")
if PRODUCTION_APP_HOST not in {"0", "1"} or (PRODUCTION_APP_HOST == "1" and FEEDBACK_WORKER_HOST):
    raise ImproperlyConfigured("PRODUCTION_APP_HOST must identify only the application host")
PRODUCTION_APP_HOST = PRODUCTION_APP_HOST == "1"
REPOSITORY_CONTROLLER_HOST = os.environ.get("REPOSITORY_CONTROLLER_HOST", "0")
REPOSITORY_ANALYSIS_ENABLED = os.environ.get("REPOSITORY_ANALYSIS_ENABLED", "0")
REPOSITORY_ADVISORIES_ENABLED = os.environ.get("REPOSITORY_ADVISORIES_ENABLED", "0")
if (REPOSITORY_CONTROLLER_HOST not in {"0", "1"} or REPOSITORY_ANALYSIS_ENABLED not in {"0", "1"} or REPOSITORY_ADVISORIES_ENABLED not in {"0", "1"}
    or REPOSITORY_CONTROLLER_HOST == "1" and (PRODUCTION_APP_HOST or FEEDBACK_WORKER_HOST)):
    raise ImproperlyConfigured("Repository controller must be a separate dedicated host; analysis flags use0/1")
REPOSITORY_CONTROLLER_HOST = REPOSITORY_CONTROLLER_HOST == "1"
REPOSITORY_ANALYSIS_ENABLED = REPOSITORY_ANALYSIS_ENABLED == "1"
REPOSITORY_ADVISORIES_ENABLED = REPOSITORY_ADVISORIES_ENABLED == "1"
REPOSITORY_ADVISORY_REVIEW_REFERENCE = os.environ.get("REPOSITORY_ADVISORY_REVIEW_REFERENCE", "")
REPOSITORY_CONTROLLER_ID = os.environ.get("REPOSITORY_CONTROLLER_ID", "")
REPOSITORY_RUNNER_IMAGE = os.environ.get("REPOSITORY_RUNNER_IMAGE", "")
REPOSITORY_ISOLATION_REVIEW_REFERENCE = os.environ.get("REPOSITORY_ISOLATION_REVIEW_REFERENCE", "")
REPOSITORY_DOCKER_SOCKET = os.environ.get("REPOSITORY_DOCKER_SOCKET", "/run/user/10001/docker.sock")
if REPOSITORY_CONTROLLER_HOST:
    _repository_ca = os.environ.get("REDIS_TLS_CA_FILE", "")
    _repository_private = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
    def _repository_private_host(host):
        try:
            return any(ipaddress.ip_address(host or "") in network for network in _repository_private)
        except ValueError:
            return False
    _repository_redis = [urlsplit(os.environ.get(key, "")) for key in ("CELERY_BROKER_URL", "DJANGO_CACHE_URL")]
    if (DEBUG or EMAIL_DELIVERY_ENABLED or EMAIL_BACKEND != "django.core.mail.backends.dummy.EmailBackend"
        or _postgres_sslmode != "verify-full" or not _repository_private_host(DATABASES["default"]["HOST"])
        or not _repository_ca.startswith("/")
        or any(url.scheme != "rediss" or not _repository_private_host(url.hostname) or not url.username or not url.password
            or parse_qs(url.query).get("ssl_cert_reqs") != ["required"]
            or parse_qs(url.query).get("ssl_ca_certs") != [_repository_ca] for url in _repository_redis)):
        raise ImproperlyConfigured("Dedicated repository controller requires private verified-TLS DB/Redis and disabled mail")
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_REQUIRED, "ssl_ca_certs": _repository_ca}
if SES_FEEDBACK_QUEUE_URL or SES_FEEDBACK_TOPIC_ARN:
    _ses_queue = re.fullmatch(
        r"https://sqs\.([a-z0-9-]{5,32})\.amazonaws\.com/([0-9]{12})/[A-Za-z0-9_-]{1,80}",
        SES_FEEDBACK_QUEUE_URL,
    )
    _ses_topic = re.fullmatch(
        r"arn:aws:sns:([a-z0-9-]{5,32}):([0-9]{12}):[A-Za-z0-9_-]{1,100}",
        SES_FEEDBACK_TOPIC_ARN,
    )
    if (not EMAIL_DELIVERY_ENABLED or not _ses_queue or not _ses_topic
        or _ses_queue.group(1, 2) != _ses_topic.group(1, 2)
        or _ses_queue.group(1) != SES_FEEDBACK_REGION):
        raise ImproperlyConfigured("SES feedback requires a matching private queue, topic and AWS region")
EMAIL_USE_TLS = not DEBUG and EMAIL_DELIVERY_ENABLED
EMAIL_TIMEOUT = 10
try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT") or "0")
    if not DEBUG and EMAIL_DELIVERY_ENABLED:
        validate_email(DEFAULT_FROM_EMAIL)
except (ValueError, ValidationError) as error:
    raise ImproperlyConfigured("Configure a valid SMTP port and sender address") from error
if not DEBUG and EMAIL_DELIVERY_ENABLED and (
    not EMAIL_HOST or EMAIL_HOST.lower() in {"localhost", "127.0.0.1", "::1"}
    or any(char in EMAIL_HOST for char in " \t\r\n/@")
    or EMAIL_HOST != f"email-smtp.{SES_FEEDBACK_REGION}.amazonaws.com"
    or not re.fullmatch(r"[a-z0-9-]{5,32}", SES_FEEDBACK_REGION)
    or EMAIL_PORT not in {587, 2587} or not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD
):
    raise ImproperlyConfigured("Configure a regional authenticated SES STARTTLS relay and sender outside development")
if FEEDBACK_WORKER_HOST or PRODUCTION_APP_HOST:
    _api_origin = os.environ.get("API_ORIGIN", "")
    _api_url = urlsplit(_api_origin)
    _public_host = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+").fullmatch
    if (not _frontend_url.hostname or not _public_host(_frontend_url.hostname)
        or not _api_url.hostname or not _public_host(_api_url.hostname)
        or FRONTEND_ORIGIN != f"https://{_frontend_url.hostname}"
        or _api_origin != f"https://{_api_url.hostname}"
        or _api_url.hostname == _frontend_url.hostname
        or len(ALLOWED_HOSTS) != 2
        or set(ALLOWED_HOSTS) != {_frontend_url.hostname, _api_url.hostname}
        or CSRF_TRUSTED_ORIGINS != [FRONTEND_ORIGIN]):
        raise ImproperlyConfigured("Production browser hosts and CSRF origin must be the exact public/API HTTPS pair")
    _private_ranges = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))

    def _private_host(host):
        try:
            address = ipaddress.ip_address(host or "")
        except ValueError:
            return False
        return any(address in network for network in _private_ranges)

    _redis_ca = os.environ.get("REDIS_TLS_CA_FILE", "")
    _redis_broker = urlsplit(os.environ.get("CELERY_BROKER_URL", ""))
    _redis_cache = urlsplit(os.environ.get("DJANGO_CACHE_URL", ""))
    if (DEBUG or os.environ.get("ARTIFACT_STORAGE_BACKEND") != "s3" or not SES_FEEDBACK_REGION
        or _postgres_sslmode != "verify-full" or not _redis_ca.startswith("/")
        or any(url.scheme != "rediss" or not url.hostname or not url.username or not url.password
               or parse_qs(url.query).get("ssl_cert_reqs") != ["required"]
               or parse_qs(url.query).get("ssl_ca_certs") != [_redis_ca]
               for url in (_redis_broker, _redis_cache))):
        raise ImproperlyConfigured("Production services require verified TLS DB/Redis and S3")
    if FEEDBACK_WORKER_HOST and (not SES_FEEDBACK_QUEUE_URL or not SES_FEEDBACK_TOPIC_ARN
        or not _private_host(DATABASES["default"]["HOST"])
        or not all(_private_host(url.hostname) for url in (_redis_broker, _redis_cache))):
        raise ImproperlyConfigured("Feedback worker requires private remote DB/Redis and SES queue")
    if PRODUCTION_APP_HOST and (SES_FEEDBACK_QUEUE_URL or SES_FEEDBACK_TOPIC_ARN
        or DATABASES["default"]["HOST"] != "postgres"
        or any(url.hostname != "redis" for url in (_redis_broker, _redis_cache))):
        raise ImproperlyConfigured("Application host must use local Docker DB/Redis without feedback IAM")
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_REQUIRED, "ssl_ca_certs": _redis_ca}

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
    raise ImproperlyConfigured("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"safe_request": {"()": "config.observability.SafeRequestLogFilter"}},
    "formatters": {"json": {"()": "config.observability.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["safe_request"],
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        name: {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False}
        for name in (
            "django", "django.server", "organicseoops", "celery", "celery.task",
            "multiprocessing", "gunicorn.error", "gunicorn.access",
        )
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}

# The private service name fails closed outside Compose; set an explicit broker
# when running local workers. No broker connection is needed for Django checks.
WEEKLY_SUMMARY_DELIVERY_ENABLED = os.environ.get("WEEKLY_SUMMARY_DELIVERY_ENABLED", "0") == "1"
ALERT_DIGEST_DELIVERY_ENABLED = os.environ.get("ALERT_DIGEST_DELIVERY_ENABLED", "0") == "1"
CRUX_ALERT_DELIVERY_ENABLED = os.environ.get("CRUX_ALERT_DELIVERY_ENABLED", "0") == "1"
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_QUEUES = tuple(Queue(name, routing_key=name) for name in ("default", "ai", "crawl", "audit", "repository"))
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_DEFAULT_ROUTING_KEY = "default"
CELERY_TASK_CREATE_MISSING_QUEUES = False
CELERY_TASK_ROUTES = {
    "jobs.send_daily_crux_digest": {"queue": "default"},
    "jobs.scan_daily_crux_digests": {"queue": "default"},
    "jobs.send_daily_alert_digest": {"queue": "default"},
    "jobs.scan_daily_alert_digests": {"queue": "default"},
    "jobs.send_weekly_summary": {"queue": "default"},
    "jobs.scan_weekly_summaries": {"queue": "default"},
    "jobs.verify_authority_link_source": {"queue": "crawl"},
    "jobs.collect_competitor_root": {"queue": "crawl"},
    "jobs.collect_competitor_schema_root": {"queue": "crawl"},
    "jobs.collect_competitor_links_root": {"queue": "crawl"},
    "jobs.collect_competitor_page_destinations": {"queue": "crawl"},
    "jobs.collect_competitor_lighthouse": {"queue": "audit"},
    "jobs.collect_competitor_page_formats": {"queue": "crawl"},
    "jobs.collect_competitor_page_dates": {"queue": "crawl"},
    "jobs.collect_competitor_page_headings": {"queue": "crawl"},
    "jobs.collect_competitor_page": {"queue": "crawl"},
    "jobs.synthesize_competitor_pair": {"queue": "ai"},
    "jobs.classify_competitor_heading_topics": {"queue": "ai"},
    "jobs.synthesize_competitor_headings_pair": {"queue": "ai"},
    "jobs.sample_ai_visibility": {"queue": "ai"},
    "jobs.import_bot_logs": {"queue": "default"},
    "jobs.sync_yandex": {"queue": "default"},
    "jobs.collect_serp": {"queue": "default"},
    "jobs.analyze_repository": {"queue": "repository"},
    "jobs.recover_repository": {"queue": "repository"},
    "jobs.execute_crawl": {"queue": "crawl"},
    "jobs.execute_render": {"queue": "crawl"},
    "jobs.verify_project_origin": {"queue": "audit"},
    "jobs.collect_passive_headers": {"queue": "audit"},
    "jobs.collect_passive_tls": {"queue": "audit"},
    "jobs.collect_passive_resources": {"queue": "audit"},
    "jobs.collect_passive_redirects": {"queue": "audit"},
    "jobs.collect_passive_http_redirects": {"queue": "audit"},
    "jobs.collect_passive_redirect_chain": {"queue": "audit"},
    "tenancy.capture_customer_snapshot": {"queue": "audit"},
    "jobs.research_topic": {"queue": "ai"},
    "jobs.generate_content": {"queue": "ai"},
}
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_IGNORE_RESULT = True
CELERY_RESULT_BACKEND = None
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "customer-export-copy-expiry": {"task": "tenancy.purge_expired_customer_copies", "schedule": 3600.0,
                                    "options": {"queue": "default"}},
    "public-contact-expiry": {"task": "tenancy.purge_public_contact", "schedule": 3600.0,
                              "options": {"queue": "default"}},
    "retained-trial-identity-expiry": {"task": "accounts.purge_retained_trial_identities", "schedule": 3600.0,
                                     "options": {"queue": "default"}},
    "optional-daily-crux-digests": {"task": "jobs.scan_daily_crux_digests", "schedule": 3600.0,
                                   "options": {"queue": "default"}},
    "optional-daily-alert-digests": {"task": "jobs.scan_daily_alert_digests", "schedule": 3600.0,
                                    "options": {"queue": "default"}},
    "optional-weekly-summaries": {"task": "jobs.scan_weekly_summaries", "schedule": 3600.0,
                                 "options": {"queue": "default"}},
    "public-analytics-expiry": {"task": "tenancy.purge_public_analytics", "schedule": 3600.0,
                                "options": {"queue": "default"}},
    "due-diagnostic-schedules": {"task": "jobs.schedule_due", "schedule": 60.0, "options": {"queue": "default"}},
    "recover-jobs": {"task": "jobs.reconcile", "schedule": 60.0, "options": {"queue": "default"}},
    "organization-notices": {"task": "tenancy.schedule_organization_notices", "schedule": 3600.0,
                             "options": {"queue": "default"}},
    "ses-feedback": {"task": "tenancy.poll_ses_feedback", "schedule": 60.0,
                     "options": {"queue": "default"}},
}

# Internal cost-unit/slot ceilings only; public plans and provider prices are P3A/P05 decisions.
INTERNAL_ORG_MONTHLY_UNITS = 100
INTERNAL_PROJECT_MONTHLY_UNITS = 40
INTERNAL_PROVIDER_MONTHLY_UNITS = 60
INTERNAL_ORG_ACTIVE_JOBS = 4
INTERNAL_PROJECT_ACTIVE_JOBS = 2
INTERNAL_PROVIDER_ACTIVE_JOBS = 2
