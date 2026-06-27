import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class ExitType(str, enum.Enum):
    RESIGNATION = "resignation"
    TERMINATION = "termination"
    RETIREMENT = "retirement"
    ABANDONMENT = "abandonment"
    CONTRACT_END = "contract_end"
    DEATH = "death"


class ExitStatus(str, enum.Enum):
    INITIATED = "initiated"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    IN_CLEARANCE = "in_clearance"
    FNF_PENDING = "fnf_pending"
    FNF_DONE = "fnf_done"
    COMPLETED = "completed"


class ExitRequest(TenantMixin, BaseModel):
    __tablename__ = "exit_requests"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    exit_type = Column(Enum(ExitType), nullable=False)
    resignation_date = Column(Date)
    last_working_date = Column(Date)
    notice_period_days = Column(Integer)
    notice_waived = Column(Boolean, default=False)
    notice_waiver_reason = Column(Text)
    reason = Column(Text, nullable=False)
    remarks = Column(Text)
    status = Column(Enum(ExitStatus), default=ExitStatus.INITIATED, nullable=False)
    initiated_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    rejection_reason = Column(Text)
    handover_employee_id = Column(GUID(), ForeignKey("employees.id"))
    exit_interview_done = Column(Boolean, default=False)
    exit_interview_notes = Column(Text)
    rehire_eligible = Column(Boolean, default=True)
    rehire_remarks = Column(Text)

    clearance_items = relationship("ExitClearance", back_populates="exit_request", cascade="all, delete-orphan")
    fnf_settlement = relationship("FnFSettlement", back_populates="exit_request", uselist=False)


class ExitClearance(TenantMixin, BaseModel):
    __tablename__ = "exit_clearances"

    exit_request_id = Column(GUID(), ForeignKey("exit_requests.id"), nullable=False, index=True)
    item_name = Column(String(200), nullable=False)
    department = Column(String(100))
    assignee_id = Column(GUID(), ForeignKey("employees.id"))
    status = Column(String(20), default="pending")
    completed_at = Column(db.DateTime(timezone=True))
    remarks = Column(Text)
    is_mandatory = Column(Boolean, default=True)

    exit_request = relationship("ExitRequest", back_populates="clearance_items")


class FnFSettlement(TenantMixin, BaseModel):
    __tablename__ = "fnf_settlements"

    exit_request_id = Column(GUID(), ForeignKey("exit_requests.id"), nullable=False, unique=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    salary_days = Column(Numeric(5, 2))
    salary_amount = Column(Numeric(12, 2), default=0)
    leave_encashment_days = Column(Numeric(5, 2))
    leave_encashment_amount = Column(Numeric(12, 2), default=0)
    gratuity_amount = Column(Numeric(12, 2), default=0)
    bonus_amount = Column(Numeric(12, 2), default=0)
    reimbursements = Column(Numeric(12, 2), default=0)
    advance_recovery = Column(Numeric(12, 2), default=0)
    loan_recovery = Column(Numeric(12, 2), default=0)
    notice_pay_recovery = Column(Numeric(12, 2), default=0)
    tds_on_fnf = Column(Numeric(12, 2), default=0)
    other_deductions = Column(Numeric(12, 2), default=0)
    other_earnings = Column(Numeric(12, 2), default=0)
    net_payable = Column(Numeric(12, 2), default=0)
    calculation_notes = Column(JSON, default=dict)
    status = Column(String(20), default="draft")
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    paid_at = Column(db.DateTime(timezone=True))
    pdf_url = Column(String(500))

    exit_request = relationship("ExitRequest", back_populates="fnf_settlement")


class DocumentTemplate(TenantMixin, BaseModel):
    """HR letter templates (offer, experience, appraisal, salary cert, etc.)"""
    __tablename__ = "document_templates"

    name = Column(String(200), nullable=False)
    type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    variables = Column(JSON, default=list)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_by_id = Column(GUID(), ForeignKey("employees.id"))


class GeneratedDocument(TenantMixin, BaseModel):
    """All letters and documents generated for employees."""
    __tablename__ = "generated_documents"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    template_id = Column(GUID(), ForeignKey("document_templates.id"))
    document_type = Column(String(50), nullable=False)
    title = Column(String(300), nullable=False)
    pdf_url = Column(String(500))
    content_snapshot = Column(Text)
    generated_by_id = Column(GUID(), ForeignKey("employees.id"))
    signed_at = Column(db.DateTime(timezone=True))
    signature_url = Column(String(500))
    is_revoked = Column(Boolean, default=False)
    revoked_reason = Column(Text)
