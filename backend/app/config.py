import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Core ──────────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-64-chars-min")
    JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-jwt-secret-64-chars-min")
    JWT_ACCESS_EXPIRES = timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "15")))
    JWT_REFRESH_EXPIRES = timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "30")))
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = False
    TESTING = False

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(os.path.dirname(__file__), '../../data/atlon.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TYPE = "RedisCache"
    CACHE_REDIS_URL = REDIS_URL
    CACHE_DEFAULT_TIMEOUT = 300

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATELIMIT_STORAGE_URI = REDIS_URL
    RATELIMIT_DEFAULT = "200 per minute"
    RATELIMIT_HEADERS_ENABLED = True

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
    FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@atlon.in")
    FROM_NAME = os.environ.get("FROM_NAME", "Atlon HRMS")

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "")
    WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "atlon_wa_verify")

    # ── Storage ───────────────────────────────────────────────────────────────
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")  # local | s3 | minio
    STORAGE_LOCAL_PATH = os.environ.get("STORAGE_LOCAL_PATH", "./data/uploads")
    AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY", "")
    AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY", "")
    AWS_BUCKET = os.environ.get("AWS_BUCKET", "atlon-hrms")
    AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

    # ── Super Admin ───────────────────────────────────────────────────────────
    SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "admin@atlon.in")
    SUPER_ADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASSWORD", "AtlonAdmin@123")

    # ── Billing ───────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

    # ── Sentry ────────────────────────────────────────────────────────────────
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

    # ── Security ──────────────────────────────────────────────────────────────
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_LENGTH = 128
    PASSWORD_REQUIRE_UPPERCASE = True
    PASSWORD_REQUIRE_LOWERCASE = True
    PASSWORD_REQUIRE_DIGIT = True
    PASSWORD_REQUIRE_SPECIAL = True
    PASSWORD_HISTORY_COUNT = 5
    PASSWORD_EXPIRY_DAYS = 90  # 0 = never
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 30
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # ── Feature Flags ─────────────────────────────────────────────────────────
    FEATURE_MFA = True
    FEATURE_BIOMETRIC = True
    FEATURE_WHATSAPP = True
    FEATURE_RECRUITMENT = True
    FEATURE_LMS = True
    FEATURE_EXPENSE = True
    FEATURE_ASSET = True
    FEATURE_VISITOR = True
    FEATURE_BILLING = True

    # ── Domain ────────────────────────────────────────────────────────────────
    BASE_DOMAIN = os.environ.get("BASE_DOMAIN", "atlon.in")
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5000")

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    # Use in-memory rate limit storage when Redis isn't running locally
    RATELIMIT_STORAGE_URI = "memory://"


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_ECHO = False
    PASSWORD_EXPIRY_DAYS = 90


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # StaticPool: all connections share one in-memory DB so create_all() is visible to all sessions
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": __import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    }
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
    CELERY_TASK_ALWAYS_EAGER = True


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
