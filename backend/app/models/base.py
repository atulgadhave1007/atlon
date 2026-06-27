import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, CHAR
from app.extensions import db


class GUID(TypeDecorator):
    """Platform-independent UUID type. Uses PostgreSQL's UUID natively,
    falls back to CHAR(36) on SQLite."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID())
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(value)
        return value


def now_utc():
    return datetime.now(timezone.utc)


class BaseModel(db.Model):
    """Abstract base with UUID PK, timestamps, and soft-delete."""
    __abstract__ = True

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = now_utc()

    def to_dict(self):
        result = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name)
            if isinstance(val, datetime):
                val = val.isoformat()
            elif isinstance(val, uuid.UUID):
                val = str(val)
            result[col.name] = val
        return result

    @classmethod
    def active(cls):
        return cls.query.filter_by(is_deleted=False)


class TenantMixin:
    """Adds tenant_id to any model for multi-tenant isolation."""
    tenant_id = Column(GUID(), db.ForeignKey("tenants.id"), nullable=False, index=True)
