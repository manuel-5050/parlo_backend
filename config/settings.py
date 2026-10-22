from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, []),
)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "users",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
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

DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework and JWT ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": "120/min",
        "anon": "30/min",
        "signup": env("SIGNUP_RATE", default="5/hour"),
        "login": "10/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# --- CORS (the React dev server) ---
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# --- Celery (background jobs) ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_TRACK_STARTED = True

# --- AI keys (used in later steps) ---
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# --- Parlo apps and limits ---
INSTALLED_APPS += ["chatbots"]
MAX_BOTS_PER_USER = env.int("MAX_BOTS_PER_USER", default=5)
MAX_SOURCES_PER_BOT = env.int("MAX_SOURCES_PER_BOT", default=20)
MAX_SOURCE_CHARS = env.int("MAX_SOURCE_CHARS", default=100000)

# --- Knowledge processing ---
# "gemini" uses Google's embeddings. "fake" is free and offline, for development.
EMBEDDING_BACKEND = env("EMBEDDING_BACKEND", default="gemini" if GEMINI_API_KEY else "fake")
GEMINI_EMBEDDING_MODEL = env("GEMINI_EMBEDDING_MODEL", default="gemini-embedding-2")
CHUNK_MAX_CHARS = env.int("CHUNK_MAX_CHARS", default=1000)
CHUNK_OVERLAP = env.int("CHUNK_OVERLAP", default=150)

# --- Chat ---
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*default_headers, "x-bot-key")
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["chat"] = env("CHAT_RATE", default="20/min")

# "gemini" uses Google's models. "fake" is free and offline, for development.
LLM_BACKEND = env("LLM_BACKEND", default="gemini" if GEMINI_API_KEY else "fake")
GEMINI_CHAT_MODEL = env("GEMINI_CHAT_MODEL", default="gemini-3.5-flash-lite")
CHAT_MAX_OUTPUT_TOKENS = env.int("CHAT_MAX_OUTPUT_TOKENS", default=1024)
CHAT_TOP_K = env.int("CHAT_TOP_K", default=5)
CHAT_HISTORY_MESSAGES = env.int("CHAT_HISTORY_MESSAGES", default=6)
CHAT_MAX_MESSAGE_CHARS = env.int("CHAT_MAX_MESSAGE_CHARS", default=1000)
CHAT_MAX_CONVERSATION_MESSAGES = env.int("CHAT_MAX_CONVERSATION_MESSAGES", default=40)
MAX_MESSAGES_PER_BOT_PER_DAY = env.int("MAX_MESSAGES_PER_BOT_PER_DAY", default=500)

# --- Widget ---
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["widget"] = env("WIDGET_RATE", default="60/min")

# --- MCP server (for Alexa+ and other assistants) ---
MCP_RATE_PER_MINUTE = env.int("MCP_RATE_PER_MINUTE", default=30)
# Hosts the MCP server answers to (protects against DNS rebinding). Add your public domain.
MCP_ALLOWED_HOSTS = env.list("MCP_ALLOWED_HOSTS", default=["localhost:*", "127.0.0.1:*", "mcp:*"])
MCP_ALLOWED_ORIGINS = env.list("MCP_ALLOWED_ORIGINS", default=[])
# False lets several requests use the database at once. Tests switch it to True.
MCP_THREAD_SENSITIVE = env.bool("MCP_THREAD_SENSITIVE", default=False)

# --- Alexa+ simulator (development only) ---
ALEXA_SIM_MCP_URL = env("ALEXA_SIM_MCP_URL", default="http://mcp:8002/mcp")
