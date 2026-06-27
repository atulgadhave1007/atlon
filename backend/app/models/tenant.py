from sqlalchemy import Column, String, Integer, Numeric, Boolean, Text, Enum, JSON
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, GUID
import enum


class PlanTier(str, enum.Enum):
    STARTER = "starter"
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class TenantStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class CountryCode(str, enum.Enum):
    IN = "IN"
    AE = "AE"
    US = "US"
    GB = "GB"
    SG = "SG"
    AU = "AU"


class Plan(BaseModel):
    __tablename__ = "plans"

    name = Column(String(50), nullable=False, unique=True)
    tier = Column(Enum(PlanTier), nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text)
    price_monthly_inr = Column(Numeric(10, 2), default=0)
    price_monthly_usd = Column(Numeric(10, 2), default=0)
    price_per_employee_inr = Column(Numeric(8, 2), default=0)
    price_per_employee_usd = Column(Numeric(8, 2), default=0)
    max_employees = Column(Integer, default=100)
    max_admins = Column(Integer, default=5)
    features = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    trial_days = Column(Integer, default=14)

    tenants = relationship("Tenant", back_populates="plan", lazy="dynamic")


class Tenant(BaseModel):
    __tablename__ = "tenants"

    slug = Column(String(63), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    legal_name = Column(String(200))
    logo_url = Column(String(500))
    bg_image_url = Column(String(500))
    primary_color = Column(String(7), default="#1a56db")
    custom_domain = Column(String(200), unique=True)
    country = Column(Enum(CountryCode), nullable=False, default=CountryCode.IN)
    timezone = Column(String(50), default="Asia/Kolkata")
    currency = Column(String(3), default="INR")
    date_format = Column(String(20), default="DD/MM/YYYY")
    fiscal_year_start = Column(Integer, default=4)
    status = Column(Enum(TenantStatus), default=TenantStatus.TRIAL, nullable=False)
    plan_id = Column(GUID(), db.ForeignKey("plans.id"), nullable=True)
    trial_ends_at = Column(db.DateTime(timezone=True))
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    pincode = Column(String(20))
    phone = Column(String(20))
    email = Column(String(200))
    website = Column(String(500))
    gstin = Column(String(20))
    pan = Column(String(20))
    tan = Column(String(20))
    pf_number = Column(String(50))
    esi_number = Column(String(50))
    lwf_number = Column(String(50))
    settings = Column(JSON, default=dict)
    feature_flags = Column(JSON, default=dict)
    employee_count = Column(Integer, default=0)
    active_employee_count = Column(Integer, default=0)

    plan = relationship("Plan", back_populates="tenants")
    employees = relationship("Employee", back_populates="tenant", lazy="dynamic")
    departments = relationship("Department", back_populates="tenant", lazy="dynamic")
    designations = relationship("Designation", back_populates="tenant", lazy="dynamic")
    branches = relationship("Branch", back_populates="tenant", lazy="dynamic")

    RESERVED_SLUGS = {
        "www", "api", "admin", "app", "mail", "smtp", "ftp", "cdn",
        "static", "assets", "help", "support", "billing", "portal",
        "login", "signup", "demo", "dev", "staging", "test", "atlon"
    }

    @classmethod
    def is_slug_valid(cls, slug: str) -> bool:
        if slug in cls.RESERVED_SLUGS:
            return False
        if not slug or len(slug) < 3 or len(slug) > 63:
            return False
        import re
        return bool(re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', slug))


class SuperAdmin(BaseModel):
    __tablename__ = "super_admins"

    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    mfa_secret = Column(String(100))
    mfa_enabled = Column(Boolean, default=False)
    last_login_at = Column(db.DateTime(timezone=True))
    last_login_ip = Column(String(45))

    def check_password(self, password: str) -> bool:
        import bcrypt
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    @staticmethod
    def hash_password(password: str) -> str:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
