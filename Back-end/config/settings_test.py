"""Settings for the automated test suite.

Runs with NO external services: SQLite in memory, in-process channel layer,
local-memory cache. Use it like:

    python manage.py test --settings=config.settings_test

LIMITATION: SQLite ignores SELECT ... FOR UPDATE and serialises writers, so
this profile cannot prove the concurrency guarantees (seat claiming, wallet
spends). Those tests (Phase 2/4) are marked and must be run against real
PostgreSQL with the normal settings module (see README "Testing").
"""
import os

# settings.py requires DJANGO_SECRET_KEY (no default, on purpose, so production
# fails fast). Tests supply a throw-away value that is never used elsewhere.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key-not-for-any-real-use")
os.environ.setdefault("DEBUG", "False")

from .settings import *  # noqa: E402,F401,F403

if os.environ.get("TEST_DB") == "postgres":
    # CI: real PostgreSQL so SELECT ... FOR UPDATE behaviour is actually exercised.
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "vibra"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
LIVEKIT_API_KEY = "test-key"
LIVEKIT_API_SECRET = "test-secret-test-secret-test-secret-1234"
LIVEKIT_URL = "wss://livekit.invalid"
WELCOME_COINS = 0  # keep balances in tests explicit
LIVEKIT_SYNC_ENABLED = False  # tests mock apps.rooms.voice_admin instead of calling LiveKit
SECURE_SSL_REDIRECT = False
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"anon": "100000/minute", "user": "100000/minute", "auth": "100000/minute", "chat": "100000/minute", "report": "100000/minute"},
}
LOGGING_CONFIG = None  # keep test output quiet
