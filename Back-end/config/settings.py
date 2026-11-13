from pathlib import Path

from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
PRODUCTION_DOMAIN = config("PRODUCTION_DOMAIN", default="vibra.sahilmuhd.com")


def env_list(name, default=""):
    return [item.strip() for item in config(name, default=default).split(",") if item.strip()]


ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", f"localhost,127.0.0.1,{PRODUCTION_DOMAIN}")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "apps.accounts",
    "apps.rooms",
    "apps.wallet",
    "apps.notifications",
    "apps.dms",
    "apps.perks",
    "apps.social",
    "apps.games",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="vibra"),
        "USER": config("DB_USER", default="vibra"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# Shared cache: password-reset tokens and throttle counters must be visible to
# every gunicorn/daphne worker (the default per-process locmem cache is not).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
if DEBUG and not config("USE_REDIS_IN_DEBUG", default=False, cast=bool):
    # Local dev (single process): don't require a running Redis.
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",  # basic anti-spam floor
        "auth": "10/minute",   # login / signup / guest / password reset, per IP
        "chat": "90/minute",   # room messages (list + send), per user
        "report": "20/hour",
        "upload": "20/hour",
    },
    # Number of reverse proxies in front of the app (Render = 1) so throttling
    # keys on the real client IP instead of the proxy's.
    "NUM_PROXIES": config("NUM_PROXIES", default=1, cast=int),
}

SIMPLE_JWT = {
    # Tokens carry a hash of the password, so changing it (e.g. password reset)
    # invalidates every previously issued access/refresh token.
    "CHECK_REVOKE_TOKEN": True,
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", f"https://{PRODUCTION_DOMAIN}")
# Auth is via Authorization-header JWTs, not cookies, so credentials are only
# needed for an explicit allow-list; never combine them with allow-all.
CORS_ALLOW_CREDENTIALS = not DEBUG
# In dev, also allow requests from file:// (origin=null) and any localhost port.
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Uploaded profile pictures (served by Django at /media/; small enough not to need a CDN yet).
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(config("MEDIA_ROOT", default=str(BASE_DIR / "media")))
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
# --- HTTPS / cookie hardening (production only) ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = [f"https://{PRODUCTION_DOMAIN}"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Third-party services (set real values via env in Render dashboard) ---
RAZORPAY_KEY_ID = config("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = config("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = config("RAZORPAY_WEBHOOK_SECRET", default="")

# LiveKit voice provider (or swap for Agora equivalents)
LIVEKIT_API_KEY = config("LIVEKIT_API_KEY", default="")
LIVEKIT_API_SECRET = config("LIVEKIT_API_SECRET", default="")
LIVEKIT_URL = config("LIVEKIT_URL", default="")
# Push seat/mute/kick changes to live LiveKit sessions (needs all three values above).
LIVEKIT_SYNC_ENABLED = bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET and LIVEKIT_URL)

# --- Coins & gifts ---
WELCOME_COINS = config("WELCOME_COINS", default=1000, cast=int)
# Gifts worth at least this many coins (cost x combo) are announced in every room.
GLOBAL_GIFT_MIN = config("GLOBAL_GIFT_MIN", default=2000, cast=int)

# --- Email (password reset) ---
# Set EMAIL_BACKEND to 'django.core.mail.backends.smtp.EmailBackend' in production
# and provide the SMTP_* env vars in your Render dashboard.
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Vibra <noreply@vibra.sahilmuhd.com>")
FRONTEND_URL = config("FRONTEND_URL", default=f"https://{PRODUCTION_DOMAIN}")
