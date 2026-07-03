import os
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

def _load_env_file(env_path, override_keys=False):
    if env_path.exists():
        with env_path.open() as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if override_keys or key not in os.environ:
                    os.environ[key] = value


# Load environment variables from root/backend env files if present.
_load_env_file(ROOT_DIR / ".env")
_load_env_file(BASE_DIR / ".env")
_load_env_file(BASE_DIR / ".env.mpesa", override_keys=True)

DEFAULT_SECRET_KEY = "dev-pos-secret-key-change-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
DEBUG = os.getenv("DEBUG", "True").lower() in ("1", "true", "yes")
if not DEBUG and SECRET_KEY == DEFAULT_SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set to a unique value when DEBUG=False.")

ALLOWED_HOSTS = os.getenv(
    "ALLOWED_HOSTS",
    ".vercel.app,127.0.0.1,localhost",
).split(",")

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        "https://*.vercel.app,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "pos",
    "inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.middleware.DevCorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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

def _database_from_url(database_url):
    parsed = urlparse(database_url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL must use postgres:// or postgresql://")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "OPTIONS": dict(parse_qsl(parsed.query, keep_blank_values=True)),
    }


DATABASE_URL = os.getenv("DATABASE_URL", "")
# SQLITE_PATH lets Electron point the database to the user's app-data folder
# so data survives app updates (PyInstaller temp dirs are wiped on exit).
_sqlite_path = os.getenv("SQLITE_PATH", "")
DATABASES = {
    "default": {
        **_database_from_url(DATABASE_URL),
        "CONN_MAX_AGE": 600,
    } if DATABASE_URL else {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(_sqlite_path) if _sqlite_path else BASE_DIR / "pos.sqlite3",
    }
}

# Cloud sync (desktop app) — set these in the environment to enable background sync
CLOUD_API_URL = os.getenv("CLOUD_API_URL", "").rstrip("/")
CLOUD_SYNC_TOKEN = os.getenv("CLOUD_SYNC_TOKEN", "")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 4},
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# Email (SMTP) — set these in .env to enable scheduled report delivery
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("1", "true", "yes")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@nexapos.com")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Desktop mode: serve the Vite-built SPA from dist/ via Django
DESKTOP_MODE = os.getenv("DESKTOP_MODE", "False").lower() in ("1", "true", "yes")
FRONTEND_DIST_DIR = (
    # PyInstaller bundle places it under _MEIPASS/frontend_dist
    Path(getattr(__import__("sys"), "_MEIPASS", "")) / "frontend_dist"
    if getattr(__import__("sys"), "frozen", False)
    else ROOT_DIR / "dist"
)
if DESKTOP_MODE and FRONTEND_DIST_DIR.exists():
    # WhiteNoise serves the entire frontend_dist dir at the webroot — no /static/ prefix.
    # /assets/app.js  → frontend_dist/assets/app.js  (correct JS MIME type)
    # /index.html     → frontend_dist/index.html      (correct HTML MIME type)
    # SPA routes (/pos/terminal) still fall through to SPACatchAllView in urls.py.
    WHITENOISE_ROOT = str(FRONTEND_DIST_DIR)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", str(not DEBUG)).lower() in ("1", "true", "yes")
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "False").lower() in ("1", "true", "yes")
SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "False").lower() in ("1", "true", "yes")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", str(not DEBUG)).lower() in ("1", "true", "yes")
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", str(not DEBUG)).lower() in ("1", "true", "yes")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "pos.authentication.POSBearerAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "pos.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "300/hour",
        "user": "3000/hour",
        "login": "5/minute",
    },
}

POS_AUTH_TOKEN_MAX_AGE = int(os.getenv("POS_AUTH_TOKEN_MAX_AGE", str(60 * 60)))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "loggers": {
        "pos.utils.mpesa": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "pos.views": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
