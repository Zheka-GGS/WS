import os
from pathlib import Path
from urllib.parse import unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0."
        )
    SECRET_KEY = "local-only-insecure-key-do-not-deploy"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "parking.apps.ParkingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    *([] if DEBUG else ["whitenoise.middleware.WhiteNoiseMiddleware"]),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "parking_project.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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
WSGI_APPLICATION = "parking_project.wsgi.application"
ASGI_APPLICATION = "parking_project.asgi.application"

database_url = os.environ.get("DATABASE_URL", "")
if database_url.startswith(("postgres://", "postgresql://")):
    parsed_database_url = urlparse(database_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed_database_url.path.lstrip("/")),
            "USER": unquote(parsed_database_url.username or ""),
            "PASSWORD": unquote(parsed_database_url.password or ""),
            "HOST": parsed_database_url.hostname or "localhost",
            "PORT": parsed_database_url.port or 5432,
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_DB_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uk"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
AI_SERVICE_URL = os.environ.get("AI_SERVICE_URL", "http://127.0.0.1:8001")
PARKVISION_MAX_UPLOAD_MB = int(os.environ.get("PARKVISION_MAX_UPLOAD_MB", "10"))
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "0" if DEBUG else "1") == "1"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
