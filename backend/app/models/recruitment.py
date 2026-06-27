import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class JobStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ApplicationStatus(str, enum.Enum):
    APPLIED = "applied"
    SCREENING = "screening"
    SHORTLISTED = "shortlisted"
    INTERVIEW_L1 = "interview_l1"
    INTERVIEW_L2 = "interview_l2"
    INTERVIEW_L3 = "interview_l3"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ON_HOLD = "on_hold"


class JobPosting(TenantMixin, BaseModel):
    __tablename__ = "job_postings"

    title = Column(String(200), nullable=False)
    job_code = Column(String(30), unique=True)
    department_id = Column(GUID(), ForeignKey("departments.id"))
    designation_id = Column(GUID(), ForeignKey("designations.id"))
    branch_id = Column(GUID(), ForeignKey("branches.id"))
    hiring_manager_id = Column(GUID(), ForeignKey("employees.id"))
    recruiter_id = Column(GUID(), ForeignKey("employees.id"))
    description = Column(Text, nullable=False)
    requirements = Column(Text)
    responsibilities = Column(Text)
    employment_type = Column(String(30), default="full_time")
    experience_min = Column(Integer, default=0)
    experience_max = Column(Integer)
    salary_min = Column(Numeric(12, 2))
    salary_max = Column(Numeric(12, 2))
    salary_currency = Column(String(3), default="INR")
    is_salary_visible = Column(Boolean, default=False)
    locations = Column(JSON, default=list)
    skills_required = Column(JSON, default=list)
    openings = Column(Integer, default=1)
    filled_count = Column(Integer, default=0)
    status = Column(Enum(JobStatus), default=JobStatus.DRAFT)
    published_at = Column(db.DateTime(timezone=True))
    closes_at = Column(Date)
    is_internal = Column(Boolean, default=False)
    is_remote = Column(Boolean, default=False)
    sourcing_channels = Column(JSON, default=list)
    pipeline_stages = Column(JSON, default=list)
    custom_fields = Column(JSON, default=dict)

    applications = relationship("JobApplication", back_populates="job_posting", lazy="dynamic")


class JobApplication(TenantMixin, BaseModel):
    __tablename__ = "job_applications"

    job_posting_id = Column(GUID(), ForeignKey("job_postings.id"), nullable=False, index=True)
    candidate_name = Column(String(200), nullable=False)
    candidate_email = Column(String(200), nullable=False)
    candidate_phone = Column(String(20))
    current_company = Column(String(200))
    current_designation = Column(String(200))
    current_ctc = Column(Numeric(12, 2))
    expected_ctc = Column(Numeric(12, 2))
    notice_period_days = Column(Integer)
    total_experience_years = Column(Numeric(4, 1))
    relevant_experience_years = Column(Numeric(4, 1))
    resume_url = Column(String(500), nullable=False)
    cover_letter = Column(Text)
    source = Column(String(50), default="direct")
    source_details = Column(String(200))
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.APPLIED, nullable=False)
    stage_history = Column(JSON, default=list)
    rejection_reason = Column(Text)
    referred_by_id = Column(GUID(), ForeignKey("employees.id"))
    assigned_to_id = Column(GUID(), ForeignKey("employees.id"))
    notes = Column(Text)
    tags = Column(JSON, default=list)
    custom_answers = Column(JSON, default=dict)
    applied_at = Column(db.DateTime(timezone=True), default=db.func.now())

    __table_args__ = (
        db.Index("idx_job_app_posting", "job_posting_id", "status"),
    )

    job_posting = relationship("JobPosting", back_populates="applications")
    interviews = relationship("Interview", back_populates="application")


class Interview(TenantMixin, BaseModel):
    __tablename__ = "interviews"

    application_id = Column(GUID(), ForeignKey("job_applications.id"), nullable=False, index=True)
    round_number = Column(Integer, default=1)
    round_name = Column(String(100))
    interview_type = Column(String(30), default="video")
    scheduled_at = Column(db.DateTime(timezone=True))
    duration_minutes = Column(Integer, default=60)
    meeting_link = Column(String(500))
    meeting_location = Column(Text)
    interviewers = Column(JSON, default=list)
    status = Column(String(20), default="scheduled")
    feedback = Column(JSON, default=dict)
    overall_recommendation = Column(String(20))
    overall_remarks = Column(Text)
    completed_at = Column(db.DateTime(timezone=True))
    cancelled_reason = Column(Text)

    application = relationship("JobApplication", back_populates="interviews")


class OfferLetter(TenantMixin, BaseModel):
    __tablename__ = "offer_letters"

    application_id = Column(GUID(), ForeignKey("job_applications.id"), nullable=False)
    employee_id = Column(GUID(), ForeignKey("employees.id"))
    ctc_offered = Column(Numeric(12, 2), nullable=False)
    joining_date = Column(Date, nullable=False)
    offer_expiry_date = Column(Date)
    designation_offered = Column(String(200))
    department_offered = Column(String(200))
    letter_content = Column(Text)
    pdf_url = Column(String(500))
    status = Column(String(20), default="draft")
    sent_at = Column(db.DateTime(timezone=True))
    accepted_at = Column(db.DateTime(timezone=True))
    declined_at = Column(db.DateTime(timezone=True))
    decline_reason = Column(Text)
    issued_by_id = Column(GUID(), ForeignKey("employees.id"))
