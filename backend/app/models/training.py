from sqlalchemy import Column, String, Integer, Boolean, Text, Date, JSON, ForeignKey, Numeric, Enum
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID
import enum


class CourseType(str, enum.Enum):
    VIDEO = "video"
    DOCUMENT = "document"
    LIVE_SESSION = "live_session"
    BLENDED = "blended"
    EXTERNAL = "external"


class EnrollmentStatus(str, enum.Enum):
    ENROLLED = "enrolled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class Course(TenantMixin, BaseModel):
    __tablename__ = "courses"

    title = Column(String(300), nullable=False)
    code = Column(String(30))
    description = Column(Text)
    category = Column(String(100))
    type = Column(Enum(CourseType), default=CourseType.VIDEO)
    duration_minutes = Column(Integer, default=0)
    thumbnail_url = Column(String(500))
    is_mandatory = Column(Boolean, default=False)
    is_self_enroll = Column(Boolean, default=True)
    validity_days = Column(Integer)
    passing_score = Column(Integer, default=70)
    certificate_template = Column(Text)
    skills_covered = Column(JSON, default=list)
    applicable_departments = Column(JSON, default=list)
    applicable_designations = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    external_url = Column(String(500))
    created_by_id = Column(GUID(), ForeignKey("employees.id"))

    modules = relationship("CourseModule", back_populates="course", order_by="CourseModule.sequence")
    enrollments = relationship("CourseEnrollment", back_populates="course", lazy="dynamic")


class CourseModule(TenantMixin, BaseModel):
    __tablename__ = "course_modules"

    course_id = Column(GUID(), ForeignKey("courses.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text)
    sequence = Column(Integer, default=1)
    content_type = Column(String(30))
    content_url = Column(String(500))
    content_text = Column(Text)
    duration_minutes = Column(Integer, default=0)
    is_mandatory = Column(Boolean, default=True)

    course = relationship("Course", back_populates="modules")


class CourseEnrollment(TenantMixin, BaseModel):
    __tablename__ = "course_enrollments"

    course_id = Column(GUID(), ForeignKey("courses.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.ENROLLED)
    progress_pct = Column(Numeric(5, 2), default=0)
    score = Column(Numeric(5, 2))
    enrolled_at = Column(db.DateTime(timezone=True), default=db.func.now())
    started_at = Column(db.DateTime(timezone=True))
    completed_at = Column(db.DateTime(timezone=True))
    expires_at = Column(db.DateTime(timezone=True))
    certificate_url = Column(String(500))
    enrolled_by_id = Column(GUID(), ForeignKey("employees.id"))

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "course_id", "employee_id", name="uq_enrollment"),
    )

    course = relationship("Course", back_populates="enrollments")
    progress_items = relationship("ModuleProgress", back_populates="enrollment")


class ModuleProgress(TenantMixin, BaseModel):
    __tablename__ = "module_progress"

    enrollment_id = Column(GUID(), ForeignKey("course_enrollments.id"), nullable=False, index=True)
    module_id = Column(GUID(), ForeignKey("course_modules.id"), nullable=False)
    is_completed = Column(Boolean, default=False)
    completed_at = Column(db.DateTime(timezone=True))
    time_spent_minutes = Column(Integer, default=0)
    score = Column(Numeric(5, 2))
    attempts = Column(Integer, default=0)

    enrollment = relationship("CourseEnrollment", back_populates="progress_items")


class Survey(TenantMixin, BaseModel):
    __tablename__ = "surveys"

    title = Column(String(300), nullable=False)
    description = Column(Text)
    survey_type = Column(String(50), default="general")
    is_anonymous = Column(Boolean, default=True)
    status = Column(String(20), default="draft")
    starts_at = Column(db.DateTime(timezone=True))
    ends_at = Column(db.DateTime(timezone=True))
    questions = Column(JSON, default=list)
    target_departments = Column(JSON, default=list)
    target_designations = Column(JSON, default=list)
    target_all = Column(Boolean, default=True)
    created_by_id = Column(GUID(), ForeignKey("employees.id"))
    response_count = Column(Integer, default=0)

    responses = relationship("SurveyResponse", back_populates="survey", lazy="dynamic")


class SurveyResponse(TenantMixin, BaseModel):
    __tablename__ = "survey_responses"

    survey_id = Column(GUID(), ForeignKey("surveys.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"))
    answers = Column(JSON, default=dict)
    submitted_at = Column(db.DateTime(timezone=True), default=db.func.now())
    is_anonymous = Column(Boolean, default=True)

    survey = relationship("Survey", back_populates="responses")
