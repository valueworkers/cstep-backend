from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qsl

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
DEBUG = os.getenv("DEBUG", "False") == "True"

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third party
    "django_filters",
    "django_celery_beat",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    # Local
    "accounts",
    "events",
    "registrations",
    "analytics",
    "notification",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # ← after SecurityMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cstep_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "cstep_backend.wsgi.application"
ASGI_APPLICATION = "cstep_backend.asgi.application"


# tmpPostgres = urlparse(os.getenv("DATABASE_URL"))

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': tmpPostgres.path.replace('/', ''),
#         'USER': tmpPostgres.username,
#         'PASSWORD': tmpPostgres.password,
#         'HOST': tmpPostgres.hostname,
#         'PORT': 5432,
#         'OPTIONS': dict(parse_qsl(tmpPostgres.query)),
#     }
# }

import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL"),
        conn_max_age=600,
    ),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# ─── DRF ──────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "cstep_backend.pagination.StandardResultsSetPagination",

}

# ─── JWT ──────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ─── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [{
                "address": REDIS_URL,
                "protocol": 2,
                "socket_timeout": 30,
                "socket_connect_timeout": 5,
                "retry_on_timeout": True,
                "health_check_interval": 30,
            }],
        },
    }
}

# ─── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = f"{REDIS_URL}/0"
CELERY_RESULT_BACKEND = f"{REDIS_URL}/0"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE  # keep in sync with Django's TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

# ─── FAST2SMS ────────────────────────────────────────────────────────────────────
FAST2SMS_AUTH_KEY = os.getenv("FAST2SMS_AUTH_KEY")
FAST2SMS_OTP_ID = os.getenv("FAST2SMS_OTP_ID")


EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.sendgrid.net"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "apikey"                          # literally the string "apikey"
EMAIL_HOST_PASSWORD = os.getenv("SENDGRID_API_KEY")  # your actual key goes here
DEFAULT_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")

# ─── Media Server ────────────────────────────────────────────────────────────────────
MEDIA_SERVER_WEBHOOK_SECRET = os.getenv(
    "MEDIA_SERVER_WEBHOOK_SECRET",
    "ze0!ev-x0#84$*m!78#&)fi01k)v!&o*y^&2mo^y-t^&$bw!ht"
)
MEDIA_SERVER_RTMP_BASE_URL = os.getenv(
    "MEDIA_SERVER_RTMP_BASE_URL",
    "rtmp://localhost:1935/live",
).rstrip("/")
MEDIA_SERVER_RTSP_BASE_URL = os.getenv(
    "MEDIA_SERVER_RTSP_BASE_URL",
    "rtsp://localhost:8554/live",
).rstrip("/")
MEDIA_SERVER_HLS_BASE_URL = os.getenv(
    "MEDIA_SERVER_HLS_BASE_URL",
    "http://localhost:8888/live",
).rstrip("/")
MEDIA_SERVER_WEBRTC_BASE_URL = os.getenv(
    "MEDIA_SERVER_WEBRTC_BASE_URL",
    "http://localhost:8889/live",
).rstrip("/")

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True  # Tighten in production


# ─── Static & Media ───────────────────────────────────────────────────────────

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
 
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# STATICFILES_DIRS = [BASE_DIR / "static"]      


MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

ALLOWED_HOSTS = ["*"]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "https://icas2026.cstep.in",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://icas2026.cstep.in",
]

CORS_ALLOW_CREDENTIALS = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Enable after HTTPS is confirmed working
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True