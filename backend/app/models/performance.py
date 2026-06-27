import enum
from sqlalchemy import Column, String, Integer, Boolean, Text, Date, Enum, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.extensions import db
from .base import BaseModel, TenantMixin, GUID


class AppraisalCycleStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RATING = "rating"
    CALIBRATION = "calibration"
    COMPLETED = "completed"


class GoalStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AppraisalCycle(TenantMixin, BaseModel):
    __tablename__ = "appraisal_cycles"

    name = Column(String(200), nullable=False)
    description = Column(Text)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    status = Column(Enum(AppraisalCycleStatus), default=AppraisalCycleStatus.DRAFT)
    goal_setting_deadline = Column(Date)
    self_rating_deadline = Column(Date)
    manager_rating_deadline = Column(Date)
    calibration_deadline = Column(Date)
    include_360 = Column(Boolean, default=False)
    rating_scale = Column(Integer, default=5)
    rating_labels = Column(JSON, default=dict)
    weightage_config = Column(JSON, default=dict)
    applicable_departments = Column(JSON, default=list)
    applicable_designations = Column(JSON, default=list)

    goals = relationship("Goal", back_populates="cycle")
    peer_feedbacks = relationship("PeerFeedback", back_populates="cycle")


class Goal(TenantMixin, BaseModel):
    __tablename__ = "goals"

    cycle_id = Column(GUID(), ForeignKey("appraisal_cycles.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text)
    kpi_metric = Column(String(200))
    target_value = Column(String(100))
    achieved_value = Column(String(100))
    weightage = Column(Numeric(5, 2), default=0)
    status = Column(Enum(GoalStatus), default=GoalStatus.DRAFT)
    self_rating = Column(Numeric(3, 1))
    self_remarks = Column(Text)
    manager_rating = Column(Numeric(3, 1))
    manager_remarks = Column(Text)
    final_rating = Column(Numeric(3, 1))
    final_remarks = Column(Text)
    due_date = Column(Date)

    cycle = relationship("AppraisalCycle", back_populates="goals")


class PeerFeedback(TenantMixin, BaseModel):
    __tablename__ = "peer_feedbacks"

    cycle_id = Column(GUID(), ForeignKey("appraisal_cycles.id"), nullable=False, index=True)
    subject_employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False, index=True)
    reviewer_employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    relationship_type = Column(String(50))
    requested_at = Column(db.DateTime(timezone=True), default=db.func.now())
    deadline = Column(Date)
    submitted_at = Column(db.DateTime(timezone=True))
    responses = Column(JSON, default=dict)
    overall_rating = Column(Numeric(3, 1))
    strengths = Column(Text)
    improvement_areas = Column(Text)
    is_anonymous = Column(Boolean, default=True)

    cycle = relationship("AppraisalCycle", back_populates="peer_feedbacks")
    subject = relationship("Employee", foreign_keys=[subject_employee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewer_employee_id])


class OKRObjective(TenantMixin, BaseModel):
    __tablename__ = "okr_objectives"

    title = Column(String(300), nullable=False)
    description = Column(Text)
    owner_id = Column(GUID(), ForeignKey("employees.id"), index=True)
    owner_type = Column(String(20), default="employee")
    department_id = Column(GUID(), ForeignKey("departments.id"))
    quarter = Column(String(10))
    year = Column(Integer)
    progress = Column(Numeric(5, 2), default=0)
    status = Column(String(20), default="active")
    parent_id = Column(GUID(), ForeignKey("okr_objectives.id"))

    key_results = relationship("OKRKeyResult", back_populates="objective")


class OKRKeyResult(TenantMixin, BaseModel):
    __tablename__ = "okr_key_results"

    objective_id = Column(GUID(), ForeignKey("okr_objectives.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text)
    owner_id = Column(GUID(), ForeignKey("employees.id"))
    metric_type = Column(String(30), default="percentage")
    target_value = Column(Numeric(12, 2))
    current_value = Column(Numeric(12, 2), default=0)
    start_value = Column(Numeric(12, 2), default=0)
    unit = Column(String(50))
    progress = Column(Numeric(5, 2), default=0)
    due_date = Column(Date)
    status = Column(String(20), default="active")

    objective = relationship("OKRObjective", back_populates="key_results")
    check_ins = relationship("OKRCheckIn", back_populates="key_result")


class OKRCheckIn(TenantMixin, BaseModel):
    __tablename__ = "okr_check_ins"

    key_result_id = Column(GUID(), ForeignKey("okr_key_results.id"), nullable=False, index=True)
    employee_id = Column(GUID(), ForeignKey("employees.id"), nullable=False)
    value = Column(Numeric(12, 2), nullable=False)
    notes = Column(Text)
    confidence_level = Column(Integer)

    key_result = relationship("OKRKeyResult", back_populates="check_ins")
