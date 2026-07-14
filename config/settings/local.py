from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Convenient, obviously-insecure fallback so `docker compose up` works
# out of the box without forcing a real secret to be generated first.
SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="local-insecure-secret-key-not-for-prod")
