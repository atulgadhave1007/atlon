import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Time, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    HALF_DAY = "half_day"
    LATE = "late"
    ON_LEAVE = "on_leave"
    HOLIDAY = "holiday"
    WEEKLY_OFF = "weekly_off"
    WORK_FROM_HOME = "wfh"
    ON_DUTY = "on_duty"
    COMP_OFF = "comp_off"
    REGULARIZED = "regularized"


class AttendanceSource(str, enum.Enum):
    WEB = "web"
    MOBILE = "mobile"
    BIOMETRIC = "biometric"
    GEO = "geo"
    MANUAL = "manual"
    SYSTEM = "system"


class HolidayType(str, enum.Enum):
    NATIONAL = "national"
    REGIONAL = "regional"
    OPTIONAL = "optional"
    COMPANY = "company"
    RESTRICTED = "restricted"


class Shift(TenantMixin, BaseModel):
    __tablename__ = "shifts"

    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    grace_in_minutes = Column(Integer, default=15)
    grace_out_minutes = Column(Integer, default=15)
    min_hours = Column(Numeric(4, 2), default=8.0)
    half_day_hours = Column(Numeric(4, 2), default=4.0)
    is_night_shift = Column(Boolean, default=False)
    break_duration_minutes = Column(Integer, default=60)
    overtime_eligible = Column(Boolean, default=True)
    weekoff_days = Column(JSON, default=lambda: ["saturday", "sunday"])
    is_flexible = Column(Boolean, default=False)
    flex_start_earliest = Column(Time)
    flex_start_latest = Column(Time)
    is_active = Column(Boolean, default=True)

    employee_shifts = relationship("EmployeeShift", back_populates="shift")


class EmployeeShift(TenantMixin, BaseModel):
    __tablename__ = "employee_shifts"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    shift_id = Column(GUID(), ForeignKey("shifts.id"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)

    shift = relationship("Shift", back_populates="employee_shifts")


class Attendance(TenantMixin, BaseModel):
    __tablename__ = "attendance"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    check_in = Column(db.DateTime(timezone=True))
    check_out = Column(db.DateTime(timezone=True))
    check_in_source = Column(Enum(AttendanceSource), default=AttendanceSource.WEB)
    check_out_source = Column(Enum(AttendanceSource), default=AttendanceSource.WEB)
    check_in_lat = Column(String(20))
    check_in_lng = Column(String(20))
    check_out_lat = Column(String(20))
    check_out_lng = Column(String(20))
    check_in_photo_url = Column(String(500))
    check_out_photo_url = Column(String(500))
    device_id = Column(String(100))
    status = Column(Enum(AttendanceStatus), nullable=False)
    shift_id = Column(GUID(), ForeignKey("shifts.id"))
    working_hours = Column(Numeric(5, 2))
    overtime_hours = Column(Numeric(5, 2), default=0)
    late_minutes = Column(Integer, default=0)
    early_exit_minutes = Column(Integer, default=0)
    is_regularized = Column(Boolean, default=False)
    regularization_id = Column(GUID(), ForeignKey("attendance_regularizations.id"))
    biometric_log_id = Column(String(100))
    notes = Column(Text)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "employee_id", "date", name="uq_att_emp_date"),
        db.Index("idx_att_tenant_date", "tenant_id", "date"),
        db.Index("idx_att_emp_date", "employee_id", "date"),
    )

    employee = relationship("Employee", back_populates="attendance_records")
    shift = relationship("Shift")
    regularization = relationship("AttendanceRegularization", back_populates="attendance")


class AttendanceRegularization(TenantMixin, BaseModel):
    __tablename__ = "attendance_regularizations"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    requested_check_in = Column(db.DateTime(timezone=True))
    requested_check_out = Column(db.DateTime(timezone=True))
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    reviewed_by_id = Column(GUID(), ForeignKey("employees.id"))
    reviewed_at = Column(db.DateTime(timezone=True))
    review_remarks = Column(Text)

    attendance = relationship("Attendance", back_populates="regularization", uselist=False)


class Holiday(TenantMixin, BaseModel):
    __tablename__ = "holidays"

    date = Column(Date, nullable=False)
    name = Column(String(200), nullable=False)
    type = Column(Enum(HolidayType), default=HolidayType.NATIONAL)
    is_optional = Column(Boolean, default=False)
    applicable_branches = Column(JSON, default=list)
    applicable_departments = Column(JSON, default=list)
    year = Column(Integer, nullable=False)

    __table_args__ = (
        db.Index("idx_holidays_tenant_year", "tenant_id", "year"),
    )


class Roster(TenantMixin, BaseModel):
    """Monthly roster — which shift each employee works each day."""
    __tablename__ = "rosters"

    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    schedule = Column(JSON, default=dict)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "employee_id", "year", "month", name="uq_roster_emp_month"),
    )


class BiometricDevice(TenantMixin, BaseModel):
    __tablename__ = "biometric_devices"

    serial_number = Column(String(100), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    model = Column(String(100))
    branch_id = Column(GUID(), ForeignKey("branches.id"))
    ip_address = Column(String(45))
    port = Column(Integer, default=4370)
    last_sync_at = Column(db.DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default=dict)


class BiometricLog(TenantMixin, BaseModel):
    """Raw push from ZKTeco device before processing."""
    __tablename__ = "biometric_logs"

    device_id = Column(String(100), nullable=False, index=True)
    employee_number = Column(String(30), nullable=False, index=True)
    punch_time = Column(db.DateTime(timezone=True), nullable=False)
    punch_type = Column(Integer)
    verify_type = Column(Integer)
    work_code = Column(Integer)
    raw_data = Column(JSON)
    is_processed = Column(Boolean, default=False)
    processed_at = Column(db.DateTime(timezone=True))
    attendance_id = Column(GUID(), ForeignKey("attendance.id"))

    __table_args__ = (
        db.Index("idx_bio_log_device_time", "device_id", "punch_time"),
    )
