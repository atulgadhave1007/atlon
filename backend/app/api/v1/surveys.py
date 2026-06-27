from flask import Blueprint, request, g
from app.extensions import db
from app.utils.auth import require_auth, log_action
from app.models.training import Survey, SurveyResponse
from app.models.survey import SurveyQuestion
from datetime import datetime

bp = Blueprint('surveys', __name__)


@bp.get('')
@require_auth()
def list_surveys():
    surveys = Survey.active().filter_by(tenant_id=g.tenant_id).all()
    return {'surveys': [_fmt(s) for s in surveys]}


@bp.post('')
@require_auth(roles=['hr_admin'])
def create_survey():
    d = request.get_json()
    s = Survey(
        tenant_id=g.tenant_id,
        title=d['title'],
        description=d.get('description'),
        survey_type=d.get('survey_type', 'general'),
        is_anonymous=d.get('is_anonymous', False),
        status='draft',
        target_all=d.get('target_all', True),
        target_departments=d.get('target_departments', []),
        target_designations=d.get('target_designations', []),
        created_by_id=str(g.employee.id),
    )
    db.session.add(s)
    db.session.flush()

    for i, q in enumerate(d.get('questions', [])):
        sq = SurveyQuestion(
            tenant_id=g.tenant_id,
            survey_id=str(s.id),
            question_text=q['question_text'],
            question_type=q['question_type'],
            options=q.get('options'),
            is_required=q.get('is_required', True),
            order=q.get('order', i),
            min_value=q.get('min_value'),
            max_value=q.get('max_value')
        )
        db.session.add(sq)

    log_action(g.tenant_id, g.employee.id, 'survey_created', 'survey', str(s.id))
    db.session.commit()
    return {'survey': _fmt(s)}, 201


@bp.post('/<uuid:survey_id>/publish')
@require_auth(roles=['hr_admin'])
def publish_survey(survey_id):
    s = Survey.active().filter_by(id=str(survey_id), tenant_id=g.tenant_id).first_or_404()
    s.status = 'active'
    log_action(g.tenant_id, g.employee.id, 'survey_published', 'survey', str(survey_id))
    db.session.commit()
    return {'message': 'Survey published'}


@bp.post('/<uuid:survey_id>/respond')
@require_auth()
def submit_response(survey_id):
    s = Survey.active().filter_by(id=str(survey_id), tenant_id=g.tenant_id).first_or_404()
    if s.status != 'active':
        return {'error': 'Survey is not active'}, 400

    if not s.is_anonymous:
        existing = SurveyResponse.query.filter_by(
            survey_id=str(survey_id),
            employee_id=str(g.employee.id)
        ).first()
        if existing:
            return {'error': 'Already responded to this survey'}, 409

    d = request.get_json()
    resp = SurveyResponse(
        survey_id=str(survey_id),
        tenant_id=g.tenant_id,
        employee_id=None if s.is_anonymous else str(g.employee.id),
        answers=d.get('answers', {}),
        is_anonymous=s.is_anonymous,
        submitted_at=datetime.utcnow()
    )
    db.session.add(resp)
    s.response_count = (s.response_count or 0) + 1
    db.session.commit()
    return {'message': 'Response submitted'}


@bp.get('/<uuid:survey_id>/results')
@require_auth(roles=['hr_admin'])
def survey_results(survey_id):
    s = Survey.active().filter_by(id=str(survey_id), tenant_id=g.tenant_id).first_or_404()
    responses = SurveyResponse.query.filter_by(survey_id=str(survey_id)).all()
    questions = SurveyQuestion.query.filter_by(survey_id=str(survey_id)).order_by(SurveyQuestion.order).all()

    results = {}
    for q in questions:
        qid = str(q.id)
        results[qid] = {
            'question': q.question_text,
            'type': q.question_type,
            'answers': [r.answers.get(qid) for r in responses if r.answers and qid in r.answers]
        }

    return {
        'survey': _fmt(s),
        'total_responses': len(responses),
        'results': results
    }


def _fmt(s):
    return {
        'id': str(s.id),
        'title': s.title,
        'description': s.description,
        'status': s.status,
        'is_anonymous': s.is_anonymous,
        'survey_type': s.survey_type,
        'target_all': s.target_all,
        'response_count': s.response_count or 0,
        'created_at': s.created_at.isoformat() if s.created_at else None,
    }
