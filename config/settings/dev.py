"""Development settings."""
from .base import *  # noqa: F403
from .base import BASE_DIR, env

DEBUG = True

ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Database (SQLite default for dev)
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}

# In dev, uncompressed static storage avoids missing manifest errors
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
