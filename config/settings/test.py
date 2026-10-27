"""Settings used by the automated test-suite (still PostgreSQL)."""
from .development import *  # noqa: F401,F403
import tempfile
from pathlib import Path

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast hashing for tests only
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PRIVATE_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="ocms-test-media-"))
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(PRIVATE_MEDIA_ROOT), "base_url": "/no-public-access/"},
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
LOGGING = {"version": 1, "disable_existing_loggers": False}
