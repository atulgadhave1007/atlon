import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Enum, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketCategory(TenantMixin, BaseModel):
    __tablename__ = "ticket_categories"

    name = Column(String(100), nullable=False)
    code = Column(String(20))
    description = Column(Text)
    default_assignee_id = Column(GUID(), ForeignKey("employees.id"))
    sla_hours = Column(Integer, default=24)
    is_active = Column(Boolean, default=True)


class HelpTicket(TenantMixin, BaseModel):
    __tablename__ = "help_tickets"

    ticket_number = Column(String(30), unique=True, nullable=False)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    category_id = Column(GUID(), ForeignKey("ticket_categories.id"))
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(Enum(TicketPriority), default=TicketPriority.MEDIUM)
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    assigned_to_id = Column(GUID(), ForeignKey("employees.id"))
    resolved_at = Column(db.DateTime(timezone=True))
    closed_at = Column(db.DateTime(timezone=True))
    due_at = Column(db.DateTime(timezone=True))
    resolution = Column(Text)
    satisfaction_rating = Column(Integer)
    satisfaction_comment = Column(Text)
    attachments = Column(JSON, default=list)
    tags = Column(JSON, default=list)

    __table_args__ = (
        db.Index("idx_ticket_emp", "employee_id", "status"),
    )

    employee = relationship("Employee", foreign_keys=[employee_id])
    assignee = relationship("Employee", foreign_keys=[assigned_to_id])
    category = relationship("TicketCategory")
    comments = relationship("TicketComment", back_populates="ticket", cascade="all, delete-orphan")


class TicketComment(TenantMixin, BaseModel):
    __tablename__ = "ticket_comments"

    ticket_id = Column(GUID(), ForeignKey("help_tickets.id"), nullable=False, index=True)
    author_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    comment = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False)
    attachments = Column(JSON, default=list)

    ticket = relationship("HelpTicket", back_populates="comments")
    author = relationship("Employee", foreign_keys=[author_id])


class Announcement(TenantMixin, BaseModel):
    __tablename__ = "announcements"

    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(30), default="general")
    priority = Column(String(20), default="normal")
    target_all = Column(Boolean, default=True)
    target_departments = Column(JSON, default=list)
    target_branches = Column(JSON, default=list)
    target_designations = Column(JSON, default=list)
    target_employees = Column(JSON, default=list)
    publish_at = Column(db.DateTime(timezone=True))
    expires_at = Column(db.DateTime(timezone=True))
    attachment_url = Column(String(500))
    is_pinned = Column(Boolean, default=False)
    requires_acknowledgement = Column(Boolean, default=False)
    created_by_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    view_count = Column(Integer, default=0)

    acknowledgements = relationship("AnnouncementAck", back_populates="announcement")


class AnnouncementAck(TenantMixin, BaseModel):
    __tablename__ = "announcement_acks"

    announcement_id = Column(GUID(), ForeignKey("announcements.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    acknowledged_at = Column(db.DateTime(timezone=True), default=db.func.now())

    announcement = relationship("Announcement", back_populates="acknowledgements")


class VisitorPass(TenantMixin, BaseModel):
    __tablename__ = "visitor_passes"

    visitor_name = Column(String(200), nullable=False)
    visitor_company = Column(String(200))
    visitor_phone = Column(String(20), nullable=False)
    visitor_email = Column(String(200))
    visitor_photo_url = Column(String(500))
    id_type = Column(String(50))
    id_number = Column(String(50))
    purpose = Column(Text, nullable=False)
    host_employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    branch_id = Column(GUID(), ForeignKey("branches.id"))
    check_in_at = Column(db.DateTime(timezone=True))
    check_out_at = Column(db.DateTime(timezone=True))
    expected_at = Column(db.DateTime(timezone=True))
    badge_number = Column(String(20))
    items_carried = Column(Text)
    status = Column(String(20), default="expected")
    pass_pdf_url = Column(String(500))
    notes = Column(Text)

    host = relationship("Employee", foreign_keys=[host_employee_id])
