"""Local development settings."""
from .base import *  # noqa: F401,F403
from .base import env_bool
import os

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or "dev-only-insecure-key-change-me-0123456789abcdefghijklmnop"
