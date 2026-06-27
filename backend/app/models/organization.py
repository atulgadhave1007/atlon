from sqlalchemy import Column, String, Integer, Boolean, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class Department(TenantMixin, BaseModel):
    __tablename__ = "departments"

    name = Column(String(200), nullable=False)
    code = Column(String(20))
    parent_id = Column(GUID(), ForeignKey("departments.id"), nullable=True)
    head_employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=True)
    cost_center_id = Column(GUID(), ForeignKey("cost_centers.id"), nullable=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)

    tenant = relationship("Tenant", back_populates="departments")
    parent = relationship("Department", remote_side="Department.id", backref="children")
    head_employee = relationship("Employee", foreign_keys=[head_employee_id])
    cost_center = relationship("CostCenter", back_populates="departments")


class Designation(TenantMixin, BaseModel):
    __tablename__ = "designations"

    name = Column(String(200), nullable=False)
    code = Column(String(20))
    grade = Column(String(20))
    level = Column(Integer, default=1)
    department_id = Column(GUID(), ForeignKey("departments.id"), nullable=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)

    tenant = relationship("Tenant", back_populates="designations")
    department = relationship("Department")


class Branch(TenantMixin, BaseModel):
    __tablename__ = "branches"

    name = Column(String(200), nullable=False)
    code = Column(String(20))
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(50))
    pincode = Column(String(20))
    phone = Column(String(20))
    email = Column(String(200))
    is_head_office = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    geo_lat = Column(String(20))
    geo_lng = Column(String(20))
    geo_radius_meters = Column(Integer, default=100)

    tenant = relationship("Tenant", back_populates="branches")


class CostCenter(TenantMixin, BaseModel):
    __tablename__ = "cost_centers"

    name = Column(String(200), nullable=False)
    code = Column(String(20), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)

    departments = relationship("Department", back_populates="cost_center")


class JobBand(TenantMixin, BaseModel):
    """Pay bands / grades for salary range management."""
    __tablename__ = "job_bands"

    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    min_ctc = Column(db.Numeric(12, 2))
    max_ctc = Column(db.Numeric(12, 2))
    currency = Column(String(3), default="INR")
    description = Column(Text)
