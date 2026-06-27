from flask import Blueprint, request, g
from app.extensions import db
from app.utils.auth import require_auth, log_action
from app.models.performance import OKRObjective, OKRKeyResult, OKRCheckIn

bp = Blueprint('okr', __name__)


@bp.get('')
@require_auth()
def list_objectives():
    quarter = request.args.get('quarter')
    year = request.args.get('year')
    owner = request.args.get('owner_id')

    q = OKRObjective.active().filter_by(tenant_id=g.tenant_id)
    if quarter:
        q = q.filter_by(quarter=quarter)
    if year:
        q = q.filter_by(year=int(year))
    if owner:
        q = q.filter_by(owner_id=owner)
    if g.role == 'employee':
        q = q.filter_by(owner_id=str(g.employee.id))

    return {'objectives': [_fmt_obj(o) for o in q.all()]}


@bp.post('')
@require_auth()
def create_objective():
    d = request.get_json()
    from datetime import date
    obj = OKRObjective(
        tenant_id=g.tenant_id,
        title=d['title'],
        description=d.get('description'),
        owner_id=d.get('owner_id', str(g.employee.id)),
        owner_type=d.get('owner_type', 'employee'),
        quarter=d.get('quarter'),
        year=d.get('year', date.today().year),
        status='active',
        progress=0,
        department_id=d.get('department_id'),
        parent_id=d.get('parent_id'),
    )
    db.session.add(obj)
    db.session.flush()

    for kr_data in d.get('key_results', []):
        kr = OKRKeyResult(
            tenant_id=g.tenant_id,
            objective_id=str(obj.id),
            title=kr_data['title'],
            description=kr_data.get('description'),
            metric_type=kr_data.get('kr_type', 'percentage'),
            start_value=kr_data.get('start_value', 0),
            target_value=kr_data['target_value'],
            current_value=kr_data.get('start_value', 0),
            unit=kr_data.get('unit'),
            due_date=kr_data.get('due_date'),
            status='active',
        )
        db.session.add(kr)

    log_action(g.tenant_id, g.employee.id, 'okr_created', 'okr_objective', str(obj.id))
    db.session.commit()
    return {'objective': _fmt_obj(obj)}, 201


@bp.post('/key-results/<uuid:kr_id>/checkin')
@require_auth()
def checkin(kr_id):
    kr = OKRKeyResult.query.filter_by(id=str(kr_id), tenant_id=g.tenant_id).first_or_404()
    d = request.get_json()
    from decimal import Decimal

    ci = OKRCheckIn(
        tenant_id=g.tenant_id,
        key_result_id=str(kr_id),
        employee_id=str(g.employee.id),
        value=d['value'],
        confidence_level=d.get('confidence'),
        notes=d.get('note'),
    )
    db.session.add(ci)

    kr.current_value = d['value']
    if kr.target_value and kr.target_value != 0:
        start = kr.start_value or Decimal('0')
        tv = kr.target_value
        cv = Decimal(str(d['value']))
        progress = ((cv - start) / (tv - start)) * 100
        kr.progress = min(max(progress, Decimal('0')), Decimal('100'))

    obj = OKRObjective.query.get(kr.objective_id)
    if obj and obj.key_results:
        avg = sum(float(k.progress or 0) for k in obj.key_results) / len(obj.key_results)
        obj.progress = avg

    db.session.commit()
    return {'message': 'Check-in recorded', 'progress': float(kr.progress or 0)}


@bp.get('/<uuid:obj_id>')
@require_auth()
def get_objective(obj_id):
    obj = OKRObjective.active().filter_by(id=str(obj_id), tenant_id=g.tenant_id).first_or_404()
    return _fmt_obj(obj)


def _fmt_obj(o):
    return {
        'id': str(o.id),
        'title': o.title,
        'description': o.description,
        'owner_id': str(o.owner_id) if o.owner_id else None,
        'owner_type': o.owner_type,
        'quarter': o.quarter,
        'year': o.year,
        'status': o.status,
        'progress': float(o.progress or 0),
        'department_id': str(o.department_id) if o.department_id else None,
        'key_results': [_fmt_kr(kr) for kr in (o.key_results or [])],
        'created_at': o.created_at.isoformat() if o.created_at else None,
    }


def _fmt_kr(kr):
    return {
        'id': str(kr.id),
        'title': kr.title,
        'metric_type': kr.metric_type,
        'start_value': float(kr.start_value or 0),
        'target_value': float(kr.target_value or 0),
        'current_value': float(kr.current_value or 0),
        'unit': kr.unit,
        'progress': float(kr.progress or 0),
        'due_date': str(kr.due_date) if kr.due_date else None,
    }
