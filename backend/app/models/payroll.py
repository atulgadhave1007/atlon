import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class ComponentType(str, enum.Enum):
    EARNING = "earning"
    DEDUCTION = "deduction"
    EMPLOYER_CONTRIBUTION = "employer_contribution"
    REIMBURSEMENT = "reimbursement"


class ComponentCalcType(str, enum.Enum):
    FIXED = "fixed"
    PERCENTAGE_OF_BASIC = "pct_of_basic"
    PERCENTAGE_OF_GROSS = "pct_of_gross"
    PERCENTAGE_OF_CTC = "pct_of_ctc"
    FORMULA = "formula"


class PayrollStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    PROCESSED = "processed"
    APPROVED = "approved"
    LOCKED = "locked"
    DISBURSED = "disbursed"
    REVERSED = "reversed"


class SalaryComponent(TenantMixin, BaseModel):
    __tablename__ = "salary_components"

    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    type = Column(Enum(ComponentType), nullable=False)
    calc_type = Column(Enum(ComponentCalcType), default=ComponentCalcType.FIXED)
    calc_value = Column(Numeric(10, 4), default=0)
    formula = Column(Text)
    is_statutory = Column(Boolean, default=False)
    is_taxable = Column(Boolean, default=True)
    is_visible_on_payslip = Column(Boolean, default=True)
    is_part_of_ctc = Column(Boolean, default=True)
    sequence = Column(Integer, default=100)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    applies_to_countries = Column(JSON, default=lambda: ["IN"])


class EmployeeSalary(TenantMixin, BaseModel):
    __tablename__ = "employee_salaries"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    ctc_annual = Column(Numeric(12, 2), nullable=False)
    ctc_monthly = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="INR")
    components = Column(JSON, default=dict)
    india_basic = Column(Numeric(12, 2), default=0)
    india_hra = Column(Numeric(12, 2), default=0)
    india_pf_employee = Column(Numeric(12, 2), default=0)
    india_pf_employer = Column(Numeric(12, 2), default=0)
    india_esi_employee = Column(Numeric(12, 2), default=0)
    india_esi_employer = Column(Numeric(12, 2), default=0)
    india_pt = Column(Numeric(12, 2), default=0)
    india_lwf_employee = Column(Numeric(12, 2), default=0)
    india_lwf_employer = Column(Numeric(12, 2), default=0)
    india_tds_monthly = Column(Numeric(12, 2), default=0)
    india_tax_regime = Column(String(10), default="new")
    india_professional_tax_state = Column(String(10), default="DEFAULT")
    uae_basic = Column(Numeric(12, 2), default=0)
    uae_housing = Column(Numeric(12, 2), default=0)
    uae_transport = Column(Numeric(12, 2), default=0)
    uae_other_allowances = Column(Numeric(12, 2), default=0)
    us_federal_filing_status = Column(String(20))
    us_w4_allowances = Column(Integer, default=0)
    us_additional_withholding = Column(Numeric(10, 2), default=0)
    revision_reason = Column(Text)
    revised_by_id = Column(GUID(), ForeignKey("employees.id"))
    arrears_paid = Column(Boolean, default=False)
    arrears_amount = Column(Numeric(12, 2), default=0)

    __table_args__ = (
        db.Index("idx_salary_emp", "employee_id", "effective_from"),
    )

    employee = relationship("Employee", back_populates="salary", foreign_keys=[employee_id])


class PayrollRun(TenantMixin, BaseModel):
    __tablename__ = "payroll_runs"

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    name = Column(String(100))
    status = Column(Enum(PayrollStatus), default=PayrollStatus.DRAFT, nullable=False)
    employee_count = Column(Integer, default=0)
    total_gross = Column(Numeric(14, 2), default=0)
    total_deductions = Column(Numeric(14, 2), default=0)
    total_net = Column(Numeric(14, 2), default=0)
    total_employer_contribution = Column(Numeric(14, 2), default=0)
    processing_notes = Column(Text)
    processed_at = Column(db.DateTime(timezone=True))
    processed_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    locked_at = Column(db.DateTime(timezone=True))
    locked_by_id = Column(GUID(), ForeignKey("employees.id"))
    disbursed_at = Column(db.DateTime(timezone=True))
    disbursed_by_id = Column(GUID(), ForeignKey("employees.id"))
    disbursement_reference = Column(String(100))
    payslips = relationship("Payslip", back_populates="payroll_run", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "year", "month", name="uq_payroll_run"),
    )


class Payslip(TenantMixin, BaseModel):
    __tablename__ = "payslips"

    payroll_run_id = Column(GUID(), ForeignKey("payroll_runs.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    working_days = Column(Integer, default=0)
    paid_days = Column(Numeric(5, 2), default=0)
    lop_days = Column(Numeric(5, 2), default=0)
    earnings = Column(JSON, default=dict)
    deductions = Column(JSON, default=dict)
    employer_contributions = Column(JSON, default=dict)
    gross_earnings = Column(Numeric(12, 2), default=0)
    total_deductions = Column(Numeric(12, 2), default=0)
    net_pay = Column(Numeric(12, 2), default=0)
    employer_total = Column(Numeric(12, 2), default=0)
    india_pf_employee = Column(Numeric(12, 2), default=0)
    india_pf_employer = Column(Numeric(12, 2), default=0)
    india_esi_employee = Column(Numeric(12, 2), default=0)
    india_esi_employer = Column(Numeric(12, 2), default=0)
    india_pt = Column(Numeric(12, 2), default=0)
    india_lwf = Column(Numeric(12, 2), default=0)
    india_tds = Column(Numeric(12, 2), default=0)
    india_ytd_tds = Column(Numeric(12, 2), default=0)
    india_ytd_pf = Column(Numeric(12, 2), default=0)
    uae_gratuity_provision = Column(Numeric(12, 2), default=0)
    us_social_security = Column(Numeric(12, 2), default=0)
    us_medicare = Column(Numeric(12, 2), default=0)
    us_federal_tax = Column(Numeric(12, 2), default=0)
    us_ytd_gross = Column(Numeric(12, 2), default=0)
    advance_deduction = Column(Numeric(12, 2), default=0)
    loan_deduction = Column(Numeric(12, 2), default=0)
    bonus = Column(Numeric(12, 2), default=0)
    arrears = Column(Numeric(12, 2), default=0)
    pdf_url = Column(String(500))
    is_sent_to_employee = Column(Boolean, default=False)
    sent_at = Column(db.DateTime(timezone=True))
    payment_mode = Column(String(30), default="bank_transfer")
    payment_reference = Column(String(100))
    payment_date = Column(Date)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "employee_id", "year", "month", name="uq_payslip_emp_month"),
        db.Index("idx_payslip_period", "tenant_id", "year", "month"),
    )

    payroll_run = relationship("PayrollRun", back_populates="payslips")


class SalaryAdvance(TenantMixin, BaseModel):
    __tablename__ = "salary_advances"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    requested_amount = Column(Numeric(12, 2), nullable=False)
    approved_amount = Column(Numeric(12, 2))
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    repayment_months = Column(Integer, default=1)
    repayment_start_month = Column(Integer)
    repayment_start_year = Column(Integer)
    monthly_deduction = Column(Numeric(12, 2))
    total_repaid = Column(Numeric(12, 2), default=0)
    outstanding = Column(Numeric(12, 2), default=0)
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_at = Column(db.DateTime(timezone=True))
    disbursed_at = Column(db.DateTime(timezone=True))
    notes = Column(Text)


class TaxDeclaration(TenantMixin, BaseModel):
    """India: Investment declarations for TDS computation."""
    __tablename__ = "tax_declarations"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    regime = Column(String(10), default="new")
    section_80c = Column(Numeric(10, 2), default=0)
    section_80ccd = Column(Numeric(10, 2), default=0)
    section_80d = Column(Numeric(10, 2), default=0)
    section_80e = Column(Numeric(10, 2), default=0)
    section_80g = Column(Numeric(10, 2), default=0)
    section_80tta = Column(Numeric(10, 2), default=0)
    hra_rent_paid = Column(Numeric(10, 2), default=0)
    hra_city_type = Column(String(10), default="metro")
    home_loan_interest = Column(Numeric(10, 2), default=0)
    home_loan_principal = Column(Numeric(10, 2), default=0)
    other_deductions = Column(JSON, default=dict)
    declarations = Column(JSON, default=dict)
    is_finalized = Column(Boolean, default=False)
    finalized_at = Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "employee_id", "year", name="uq_tax_decl"),
    )


class UAEGratuityRecord(TenantMixin, BaseModel):
    __tablename__ = "uae_gratuity_records"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    calculation_date = Column(Date, nullable=False)
    service_years = Column(Numeric(5, 2))
    daily_wage = Column(Numeric(10, 2))
    gratuity_amount = Column(Numeric(12, 2))
    exit_type = Column(String(30))
    is_paid = Column(Boolean, default=False)
    paid_date = Column(Date)
    payslip_id = Column(GUID(), ForeignKey("payslips.id"))
    notes = Column(Text)
