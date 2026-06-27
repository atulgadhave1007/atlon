from app.extensions import db
from app.models.base import BaseModel, TenantMixin, GUID


class SurveyQuestion(BaseModel):
    """Individual questions for a Survey (stored in training.Survey via JSON `questions` field by default).
    This model provides a normalized alternative for tenants needing granular question analytics."""
    __tablename__ = 'survey_questions'

    survey_id = db.Column(GUID(), db.ForeignKey('surveys.id'), nullable=False, index=True)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(30), nullable=False)  # text, single_choice, multiple_choice, rating, likert
    options = db.Column(db.JSON)
    is_required = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    min_value = db.Column(db.Integer)
    max_value = db.Column(db.Integer)
    tenant_id = db.Column(GUID(), db.ForeignKey('tenants.id'), nullable=False)
