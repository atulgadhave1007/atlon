import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class ExpenseStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"
    CANCELLED = "cancelled"


class ExpenseCategory(TenantMixin, BaseModel):
    __tablename__ = "expense_categories"

    name = Column(String(100), nullable=False)
    code = Column(String(20))
    description = Column(Text)
    gl_code = Column(String(30))
    requires_receipt = Column(Boolean, default=True)
    max_amount = Column(Numeric(10, 2))
    is_active = Column(Boolean, default=True)


class ExpenseClaim(TenantMixin, BaseModel):
    __tablename__ = "expense_claims"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    claim_number = Column(String(30), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(Enum(ExpenseStatus), default=ExpenseStatus.DRAFT, nullable=False)
    total_amount = Column(Numeric(12, 2), default=0)
    approved_amount = Column(Numeric(12, 2))
    currency = Column(String(3), default="INR")
    travel_request_id = Column(GUID(), ForeignKey("travel_requests.id"))
    submitted_at = Column(db.DateTime(timezone=True))
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    rejection_reason = Column(Text)
    paid_at = Column(db.DateTime(timezone=True))
    paid_via_payroll = Column(Boolean, default=False)
    payment_reference = Column(String(100))

    items = relationship("ExpenseItem", back_populates="claim", cascade="all, delete-orphan")
    travel_request = relationship("TravelRequest", back_populates="expense_claims", foreign_keys=[travel_request_id])


class ExpenseItem(TenantMixin, BaseModel):
    __tablename__ = "expense_items"

    claim_id = Column(GUID(), ForeignKey("expense_claims.id"), nullable=False, index=True)
    category_id = Column(GUID(), ForeignKey("expense_categories.id"))
    description = Column(String(300), nullable=False)
    expense_date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="INR")
    receipt_url = Column(String(500))
    vendor = Column(String(200))
    notes = Column(Text)
    is_billable = Column(Boolean, default=False)
    project_id = Column(String(100))

    claim = relationship("ExpenseClaim", back_populates="items")
    category = relationship("ExpenseCategory")


class TravelRequest(TenantMixin, BaseModel):
    __tablename__ = "travel_requests"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    request_number = Column(String(30), unique=True, nullable=False)
    purpose = Column(String(300), nullable=False)
    from_city = Column(String(100), nullable=False)
    to_city = Column(String(100), nullable=False)
    departure_date = Column(Date, nullable=False)
    return_date = Column(Date, nullable=False)
    travel_mode = Column(String(30))
    accommodation_required = Column(Boolean, default=False)
    estimated_cost = Column(Numeric(12, 2))
    status = Column(String(20), default="pending")
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    rejection_reason = Column(Text)
    booking_details = Column(JSON, default=dict)
    notes = Column(Text)
    expense_claims = relationship("ExpenseClaim", back_populates="travel_request")


class AssetCategory(TenantMixin, BaseModel):
    __tablename__ = "asset_categories"

    name = Column(String(100), nullable=False)
    code = Column(String(20))
    description = Column(Text)
    depreciation_method = Column(String(30))
    useful_life_years = Column(Integer)
    is_active = Column(Boolean, default=True)


class Asset(TenantMixin, BaseModel):
    __tablename__ = "assets"

    asset_code = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    category_id = Column(GUID(), ForeignKey("asset_categories.id"))
    brand = Column(String(100))
    model = Column(String(100))
    serial_number = Column(String(100))
    purchase_date = Column(Date)
    purchase_cost = Column(Numeric(12, 2))
    current_value = Column(Numeric(12, 2))
    location = Column(String(200))
    branch_id = Column(GUID(), ForeignKey("branches.id"))
    status = Column(String(30), default="available")
    assigned_to_id = Column(GUID(), ForeignKey("employees.id"))
    assigned_at = Column(db.DateTime(timezone=True))
    warranty_expiry = Column(Date)
    insurance_expiry = Column(Date)
    notes = Column(Text)
    photo_url = Column(String(500))
    document_url = Column(String(500))

    category = relationship("AssetCategory")
    assignment_history = relationship("AssetAssignment", back_populates="asset", lazy="dynamic")


class AssetAssignment(TenantMixin, BaseModel):
    __tablename__ = "asset_assignments"

    asset_id = Column(GUID(), ForeignKey("assets.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    assigned_at = Column(db.DateTime(timezone=True), nullable=False)
    returned_at = Column(db.DateTime(timezone=True))
    condition_on_assign = Column(String(50))
    condition_on_return = Column(String(50))
    assigned_by_id = Column(GUID(), ForeignKey("employees.id"))
    return_notes = Column(Text)

    asset = relationship("Asset", back_populates="assignment_history")
