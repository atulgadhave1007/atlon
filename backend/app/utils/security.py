import re
import bleach
import unicodedata
import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


RESERVED_SLUGS = {
    "www", "api", "admin", "app", "mail", "smtp", "ftp", "cdn",
    "static", "assets", "help", "support", "billing", "portal",
    "login", "signup", "demo", "dev", "staging", "test", "atlon",
    "dashboard", "auth", "health", "metrics", "webhook"
}


def sanitize_string(value: str, max_length: int = 500) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = bleach.clean(value, tags=[], strip=True)
    return value.strip()[:max_length]


def is_valid_email(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def is_valid_phone(phone: str) -> bool:
    if not phone:
        return False
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15


def validate_password(password: str, config: dict = None) -> list:
    """Returns list of validation errors. Empty = valid."""
    errors = []
    if not password:
        return ["Password is required"]
    min_len = config.get("PASSWORD_MIN_LENGTH", 8) if config else 8
    max_len = config.get("PASSWORD_MAX_LENGTH", 128) if config else 128
    if len(password) < min_len:
        errors.append(f"Password must be at least {min_len} characters")
    if len(password) > max_len:
        errors.append(f"Password must not exceed {max_len} characters")
    require_upper = config.get("PASSWORD_REQUIRE_UPPERCASE", True) if config else True
    require_lower = config.get("PASSWORD_REQUIRE_LOWERCASE", True) if config else True
    require_digit = config.get("PASSWORD_REQUIRE_DIGIT", True) if config else True
    require_special = config.get("PASSWORD_REQUIRE_SPECIAL", True) if config else True
    if require_upper and not re.search(r'[A-Z]', password):
        errors.append("Password must contain at least one uppercase letter")
    if require_lower and not re.search(r'[a-z]', password):
        errors.append("Password must contain at least one lowercase letter")
    if require_digit and not re.search(r'\d', password):
        errors.append("Password must contain at least one digit")
    if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;\'`~]', password):
        errors.append("Password must contain at least one special character")
    return errors


def is_valid_slug(slug: str) -> bool:
    if not slug or len(slug) < 3 or len(slug) > 63:
        return False
    if slug in RESERVED_SLUGS:
        return False
    return bool(re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', slug))


def mask_account_number(account: str) -> str:
    if not account or len(account) < 4:
        return "****"
    return "*" * (len(account) - 4) + account[-4:]


def encrypt_sensitive(value: str, key: bytes) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(key)
    return f.encrypt(value.encode()).decode()


def decrypt_sensitive(value: str, key: bytes) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(key)
    return f.decrypt(value.encode()).decode()


def generate_totp_secret() -> str:
    import pyotp
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    import pyotp
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_totp_uri(secret: str, email: str, issuer: str = "Atlon HRMS") -> str:
    import pyotp
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def generate_backup_codes(count: int = 8) -> list:
    import secrets
    return [secrets.token_hex(4).upper() for _ in range(count)]
