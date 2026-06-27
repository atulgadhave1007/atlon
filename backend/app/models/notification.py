import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Enum, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class NotificationChannel(str, enum.Enum):
    INAPP = "inapp"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    PUSH = "push"


class Notification(TenantMixin, BaseModel):
    __tablename__ = "notifications"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    type = Column(String(50), default="info")
    action_url = Column(String(500))
    entity_type = Column(String(50))
    entity_id = Column(GUID())
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(db.DateTime(timezone=True))
    channel = Column(Enum(NotificationChannel), default=NotificationChannel.INAPP)
    delivery_status = Column(String(20), default="delivered")
    extra_data = Column(JSON, default=dict)

    __table_args__ = (
        db.Index("idx_notif_emp_read", "employee_id", "is_read"),
        db.Index("idx_notif_tenant", "tenant_id", "created_at"),
    )


class NotificationTemplate(TenantMixin, BaseModel):
    __tablename__ = "notification_templates"

    event_type = Column(String(100), nullable=False)
    channel = Column(Enum(NotificationChannel), nullable=False)
    subject = Column(String(300))
    body_template = Column(Text, nullable=False)
    variables = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "event_type", "channel", name="uq_notif_tmpl"),
    )


class NotificationConfig(TenantMixin, BaseModel):
    __tablename__ = "notification_configs"

    event_type = Column(String(100), nullable=False)
    is_inapp_enabled = Column(Boolean, default=True)
    is_email_enabled = Column(Boolean, default=True)
    is_whatsapp_enabled = Column(Boolean, default=False)
    is_sms_enabled = Column(Boolean, default=False)
    is_push_enabled = Column(Boolean, default=False)
    additional_recipients = Column(JSON, default=list)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "event_type", name="uq_notif_config"),
    )


class AuditLog(BaseModel):
    """Immutable, append-only audit trail. Never soft-deleted."""
    __tablename__ = "audit_logs"

    # tenant_id is nullable here: super admin and pre-auth events have no tenant
    tenant_id = Column(GUID(), db.ForeignKey("tenants.id"), nullable=True, index=True)
    actor_id = Column(GUID(), ForeignKey("employees.id"), index=True)
    actor_email = Column(String(200))
    actor_role = Column(String(50))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100))
    entity_id = Column(GUID())
    old_values = Column(JSON)
    new_values = Column(JSON)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    request_id = Column(String(100))
    result = Column(String(20), default="success")
    error_message = Column(Text)
    duration_ms = Column(Integer)

    __table_args__ = (
        db.Index("idx_audit_tenant_time", "tenant_id", "created_at"),
        db.Index("idx_audit_entity", "entity_type", "entity_id"),
        db.Index("idx_audit_actor", "actor_id"),
    )

    def soft_delete(self):
        raise NotImplementedError("Audit logs are immutable.")


class RefreshToken(BaseModel):
    __tablename__ = "refresh_tokens"

    # tenant_id nullable: super admin refresh tokens have no tenant
    tenant_id = Column(GUID(), db.ForeignKey("tenants.id"), nullable=True, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), index=True)
    super_admin_id = Column(GUID(), ForeignKey("super_admins.id"), index=True)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    device_info = Column(String(500))
    ip_address = Column(String(45))
    expires_at = Column(db.DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(db.DateTime(timezone=True))
    last_used_at = Column(db.DateTime(timezone=True))


class DeviceSession(TenantMixin, BaseModel):
    __tablename__ = "device_sessions"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    device_id = Column(String(200), nullable=False)
    device_name = Column(String(200))
    device_type = Column(String(30))
    os = Column(String(50))
    browser = Column(String(100))
    ip_address = Column(String(45))
    last_active_at = Column(db.DateTime(timezone=True))
    is_trusted = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
