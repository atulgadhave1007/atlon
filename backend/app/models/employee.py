import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class MaritalStatus(str, enum.Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


class BloodGroup(str, enum.Enum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERN = "intern"
    CONSULTANT = "consultant"


class EmployeeStatus(str, enum.Enum):
    ACTIVE = "active"
    ON_NOTICE = "on_notice"
    PROBATION = "probation"
    ABSCONDING = "absconding"
    EXITED = "exited"
    SUSPENDED = "suspended"


class Role(str, enum.Enum):
    HR_ADMIN = "hr_admin"
    PAYROLL_ADMIN = "payroll_admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class Employee(TenantMixin, BaseModel):
    __tablename__ = "employees"

    # ── Identity ──────────────────────────────────────────────────────────────
    employee_number = Column(String(30), nullable=False)
    first_name = Column(String(100), nullable=False)
    middle_name = Column(String(100))
    last_name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    gender = Column(Enum(Gender))
    date_of_birth = Column(Date)
    blood_group = Column(Enum(BloodGroup))
    marital_status = Column(Enum(MaritalStatus))
    nationality = Column(String(100))
    religion = Column(String(50))
    disability = Column(String(200))

    # ── Contact ───────────────────────────────────────────────────────────────
    personal_email = Column(String(200))
    work_email = Column(String(200), nullable=False)
    personal_phone = Column(String(20))
    work_phone = Column(String(20))
    extension = Column(String(10))
    address_line1 = Column(Text)
    address_line2 = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(50))
    pincode = Column(String(20))
    permanent_address = Column(Text)

    # ── Employment ────────────────────────────────────────────────────────────
    date_of_joining = Column(Date, nullable=False)
    date_of_confirmation = Column(Date)
    probation_end_date = Column(Date)
    date_of_exit = Column(Date)
    employment_type = Column(Enum(EmploymentType), default=EmploymentType.FULL_TIME)
    status = Column(Enum(EmployeeStatus), default=EmployeeStatus.PROBATION, nullable=False)
    role = Column(Enum(Role), default=Role.EMPLOYEE, nullable=False)

    # ── Org Placement ─────────────────────────────────────────────────────────
    department_id = Column(GUID(), ForeignKey("departments.id"))
    designation_id = Column(GUID(), ForeignKey("designations.id"))
    branch_id = Column(GUID(), ForeignKey("branches.id"))
    reporting_manager_id = Column(GUID(), ForeignKey("employees.id"))
    dotted_manager_id = Column(GUID(), ForeignKey("employees.id"))
    cost_center_id = Column(GUID(), ForeignKey("cost_centers.id"))

    # ── Statutory Identifiers ─────────────────────────────────────────────────
    pan = Column(String(20))
    aadhaar_last4 = Column(String(4))
    uan = Column(String(20))
    pf_number = Column(String(30))
    esi_number = Column(String(30))
    passport_number = Column(String(30))
    passport_expiry = Column(Date)
    driving_license = Column(String(30))
    visa_number = Column(String(30))
    visa_expiry = Column(Date)
    emirates_id = Column(String(20))
    ssn_last4 = Column(String(4))

    # ── Profile ───────────────────────────────────────────────────────────────
    photo_url = Column(String(500))
    bio = Column(Text)
    linkedin_url = Column(String(500))
    skills = Column(JSON, default=list)
    languages = Column(JSON, default=list)

    # ── Auth ──────────────────────────────────────────────────────────────────
    password_hash = Column(String(255), nullable=False)
    password_changed_at = Column(db.DateTime(timezone=True))
    password_history = Column(JSON, default=list)
    mfa_secret = Column(String(100))
    mfa_enabled = Column(Boolean, default=False)
    mfa_backup_codes = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(db.DateTime(timezone=True))
    last_login_at = Column(db.DateTime(timezone=True))
    last_login_ip = Column(String(45))
    force_password_change = Column(Boolean, default=True)

    # ── Metadata ──────────────────────────────────────────────────────────────
    custom_fields = Column(JSON, default=dict)
    tags = Column(JSON, default=list)

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant = relationship("Tenant", back_populates="employees")
    department = relationship("Department", foreign_keys=[department_id])
    designation = relationship("Designation", foreign_keys=[designation_id])
    branch = relationship("Branch", foreign_keys=[branch_id])
    reporting_manager = relationship("Employee", foreign_keys=[reporting_manager_id], remote_side="Employee.id")
    bank_details = relationship("EmployeeBankDetail", back_populates="employee", cascade="all, delete-orphan")
    documents = relationship("EmployeeDocument", back_populates="employee", cascade="all, delete-orphan",
                             foreign_keys="[EmployeeDocument.employee_id]")
    education = relationship("EmployeeEducation", back_populates="employee", cascade="all, delete-orphan")
    experience = relationship("EmployeeExperience", back_populates="employee", cascade="all, delete-orphan")
    emergency_contacts = relationship("EmergencyContact", back_populates="employee", cascade="all, delete-orphan")
    salary = relationship("EmployeeSalary", back_populates="employee", cascade="all, delete-orphan",
                         foreign_keys="[EmployeeSalary.employee_id]")
    attendance_records = relationship("Attendance", back_populates="employee", lazy="dynamic")
    leave_balances = relationship("LeaveBalance", back_populates="employee", cascade="all, delete-orphan")
    leave_applications = relationship("LeaveApplication", back_populates="employee", lazy="dynamic",
                                      foreign_keys="LeaveApplication.employee_id")

    def check_password(self, password: str) -> bool:
        import bcrypt
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    @staticmethod
    def hash_password(password: str) -> str:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    @property
    def is_locked(self):
        from datetime import datetime, timezone
        if self.locked_until and self.locked_until > datetime.now(timezone.utc):
            return True
        return False


class EmployeeBankDetail(TenantMixin, BaseModel):
    __tablename__ = "employee_bank_details"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    bank_name = Column(String(200), nullable=False)
    account_holder_name = Column(String(200))
    account_number_encrypted = Column(String(500), nullable=False)
    account_number_last4 = Column(String(4))
    ifsc_code = Column(String(20))
    branch_name = Column(String(200))
    iban = Column(String(40))
    swift_code = Column(String(20))
    routing_number = Column(String(20))
    account_type = Column(String(50), default="savings")
    is_primary = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    employee = relationship("Employee", back_populates="bank_details")


class EmployeeDocument(TenantMixin, BaseModel):
    __tablename__ = "employee_documents"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    document_type = Column(String(100), nullable=False)
    document_name = Column(String(200), nullable=False)
    file_url = Column(String(500), nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    expiry_date = Column(Date)
    is_verified = Column(Boolean, default=False)
    verified_by_id = Column(GUID(), ForeignKey("employees.id"))
    notes = Column(Text)

    employee = relationship("Employee", back_populates="documents", foreign_keys=[employee_id])


class EmployeeEducation(TenantMixin, BaseModel):
    __tablename__ = "employee_education"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    degree = Column(String(200), nullable=False)
    field_of_study = Column(String(200))
    institution = Column(String(300), nullable=False)
    year_from = Column(Integer)
    year_to = Column(Integer)
    grade = Column(String(20))
    certificate_url = Column(String(500))

    employee = relationship("Employee", back_populates="education")


class EmployeeExperience(TenantMixin, BaseModel):
    __tablename__ = "employee_experience"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    company_name = Column(String(300), nullable=False)
    designation = Column(String(200))
    company_location = Column(String(300))
    from_date = Column(Date)
    to_date = Column(Date)
    is_current = Column(Boolean, default=False)
    reason_for_leaving = Column(Text)
    ctc = Column(Numeric(15, 2))
    manager_name = Column(String(200))
    manager_email = Column(String(200))
    manager_mobile = Column(String(20))
    reference_name = Column(String(200))
    reference_phone = Column(String(20))

    employee = relationship("Employee", back_populates="experience")


class EmergencyContact(TenantMixin, BaseModel):
    __tablename__ = "emergency_contacts"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    name = Column(String(200), nullable=False)
    relation = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    alt_phone = Column(String(20))
    email = Column(String(200))
    address = Column(Text)
    is_primary = Column(Boolean, default=False)

    employee = relationship("Employee", back_populates="emergency_contacts")


class EmployeeLifecycleEvent(TenantMixin, BaseModel):
    """Immutable audit trail of all lifecycle events."""
    __tablename__ = "employee_lifecycle_events"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    effective_date = Column(Date, nullable=False)
    from_value = Column(JSON)
    to_value = Column(JSON)
    remarks = Column(Text)
    initiated_by_id = Column(GUID(), ForeignKey("employees.id"))
    approved_by_id = Column(GUID(), ForeignKey("employees.id"))
    document_url = Column(String(500))
