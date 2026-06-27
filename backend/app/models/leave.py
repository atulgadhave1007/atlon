import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class LeaveAccrualType(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ON_JOIN = "on_join"
    MANUAL = "manual"


class LeaveApplicationStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REVOKED = "revoked"


class LeaveType(TenantMixin, BaseModel):
    __tablename__ = "leave_types"

    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    description = Column(Text)
    color = Column(String(7), default="#3b82f6")
    accrual_type = Column(Enum(LeaveAccrualType), default=LeaveAccrualType.MONTHLY)
    accrual_days_per_period = Column(Numeric(5, 2), default=1.5)
    max_balance = Column(Numeric(5, 2), default=60)
    max_carry_forward = Column(Numeric(5, 2), default=0)
    carry_forward_expiry_months = Column(Integer, default=3)
    min_days_per_application = Column(Numeric(4, 2), default=0.5)
    max_days_per_application = Column(Numeric(4, 2), default=30)
    notice_days_before = Column(Integer, default=1)
    allow_half_day = Column(Boolean, default=True)
    allow_negative = Column(Boolean, default=False)
    is_paid = Column(Boolean, default=True)
    is_encashable = Column(Boolean, default=False)
    encash_percentage = Column(Numeric(5, 2), default=100)
    requires_document = Column(Boolean, default=False)
    document_required_after_days = Column(Integer, default=3)
    applicable_genders = Column(JSON, default=lambda: ["male", "female", "other"])
    applicable_employment_types = Column(JSON, default=list)
    applicable_designations = Column(JSON, default=list)
    applicable_departments = Column(JSON, default=list)
    sandwich_policy = Column(Boolean, default=True)
    count_weekends = Column(Boolean, default=False)
    count_holidays = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    balances = relationship("LeaveBalance", back_populates="leave_type")
    applications = relationship("LeaveApplication", back_populates="leave_type")


class LeaveBalance(TenantMixin, BaseModel):
    __tablename__ = "leave_balances"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    leave_type_id = Column(GUID(), ForeignKey("leave_types.id"), nullable=False)
    year = Column(Integer, nullable=False)
    opening_balance = Column(Numeric(6, 2), default=0)
    credited = Column(Numeric(6, 2), default=0)
    availed = Column(Numeric(6, 2), default=0)
    pending = Column(Numeric(6, 2), default=0)
    lapsed = Column(Numeric(6, 2), default=0)
    encashed = Column(Numeric(6, 2), default=0)
    carry_forward = Column(Numeric(6, 2), default=0)
    manual_adjustment = Column(Numeric(6, 2), default=0)
    adjustment_remarks = Column(Text)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "employee_id", "leave_type_id", "year", name="uq_leave_bal"),
        db.Index("idx_leave_bal_emp", "employee_id", "year"),
    )

    employee = relationship("Employee", back_populates="leave_balances")
    leave_type = relationship("LeaveType", back_populates="balances")

    @property
    def balance(self):
        return float(self.opening_balance + self.credited + self.carry_forward + self.manual_adjustment - self.availed - self.pending - self.lapsed - self.encashed)


class LeaveApplication(TenantMixin, BaseModel):
    __tablename__ = "leave_applications"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    leave_type_id = Column(GUID(), ForeignKey("leave_types.id"), nullable=False)
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    from_half = Column(String(10))
    to_half = Column(String(10))
    days_count = Column(Numeric(5, 2), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(Enum(LeaveApplicationStatus), default=LeaveApplicationStatus.PENDING, nullable=False)
    contact_during_leave = Column(String(20))
    document_url = Column(String(500))
    reviewed_by_id = Column(GUID(), ForeignKey("employees.id"))
    reviewed_at = Column(db.DateTime(timezone=True))
    review_remarks = Column(Text)
    applied_at = Column(db.DateTime(timezone=True), default=db.func.now())
    cancelled_at = Column(db.DateTime(timezone=True))
    cancelled_reason = Column(Text)

    __table_args__ = (
        db.Index("idx_leave_app_emp", "employee_id"),
        db.Index("idx_leave_app_tenant", "tenant_id", "status"),
    )

    employee = relationship("Employee", back_populates="leave_applications", foreign_keys=[employee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewed_by_id])
    leave_type = relationship("LeaveType", back_populates="applications")


class LeaveAccrualLog(TenantMixin, BaseModel):
    """Audit trail for every accrual run."""
    __tablename__ = "leave_accrual_logs"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    leave_type_id = Column(GUID(), ForeignKey("leave_types.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer)
    days_accrued = Column(Numeric(5, 2), nullable=False)
    reason = Column(String(200))
    run_at = Column(db.DateTime(timezone=True), default=db.func.now())


class CompOff(TenantMixin, BaseModel):
    __tablename__ = "comp_offs"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    worked_date = Column(Date, nullable=False)
    reason = Column(Text, nullable=False)
    days_earned = Column(Numeric(4, 2), default=1.0)
    expiry_date = Column(Date)
    status = Column(String(20), default="pending")
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    leave_application_id = Column(GUID(), ForeignKey("leave_applications.id"))
