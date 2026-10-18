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

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
LIVEKIT_API_KEY = "test-key"
LIVEKIT_API_SECRET = "test-secret-test-secret-test-secret-1234"
LIVEKIT_URL = "wss://livekit.invalid"
