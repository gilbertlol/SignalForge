from .base import *  # noqa: F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="test-secret-key-not-for-prod")

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
