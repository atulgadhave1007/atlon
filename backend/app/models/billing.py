import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, GUID


class BillingCycle(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class Subscription(BaseModel):
    __tablename__ = "subscriptions"

    tenant_id = Column(GUID(), db.ForeignKey("tenants.id"), nullable=False, unique=True, index=True)
    plan_id = Column(GUID(), db.ForeignKey("plans.id"), nullable=False)
    billing_cycle = Column(Enum(BillingCycle), default=BillingCycle.MONTHLY)
    status = Column(String(20), default="trialing")
    employee_count_billed = Column(Integer, default=0)
    amount_per_period = Column(Numeric(12, 2), default=0)
    currency = Column(String(3), default="INR")
    trial_start = Column(Date)
    trial_end = Column(Date)
    current_period_start = Column(Date)
    current_period_end = Column(Date)
    cancelled_at = Column(db.DateTime(timezone=True))
    cancellation_reason = Column(Text)
    stripe_subscription_id = Column(String(100))
    stripe_customer_id = Column(String(100))
    razorpay_subscription_id = Column(String(100))
    razorpay_customer_id = Column(String(100))
    payment_gateway = Column(String(20), default="razorpay")
    extra_data = Column(JSON, default=dict)

    tenant = relationship("Tenant")
    plan = relationship("Plan")
    invoices = relationship("Invoice", back_populates="subscription", lazy="dynamic")


class Invoice(BaseModel):
    __tablename__ = "invoices"

    tenant_id = Column(GUID(), db.ForeignKey("tenants.id"), nullable=False, index=True)
    subscription_id = Column(GUID(), db.ForeignKey("subscriptions.id"), nullable=False)
    invoice_number = Column(String(30), unique=True, nullable=False)
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    period_from = Column(Date)
    period_to = Column(Date)
    employee_count = Column(Integer, default=0)
    subtotal = Column(Numeric(12, 2), default=0)
    discount_amount = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    total_amount = Column(Numeric(12, 2), default=0)
    currency = Column(String(3), default="INR")
    due_date = Column(Date)
    paid_at = Column(db.DateTime(timezone=True))
    payment_reference = Column(String(100))
    payment_gateway = Column(String(20))
    pdf_url = Column(String(500))
    line_items = Column(JSON, default=list)
    notes = Column(Text)

    subscription = relationship("Subscription", back_populates="invoices")
    tenant = relationship("Tenant")


class UsageRecord(BaseModel):
    """Daily snapshot of tenant usage for billing."""
    __tablename__ = "usage_records"

    tenant_id = Column(GUID(), db.ForeignKey("tenants.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    active_employee_count = Column(Integer, default=0)
    api_calls = Column(Integer, default=0)
    storage_mb = Column(Numeric(10, 2), default=0)
    payroll_runs = Column(Integer, default=0)
    pdf_generated = Column(Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "date", name="uq_usage_date"),
    )
