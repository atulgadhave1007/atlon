from flask import Blueprint, request, g
from app.extensions import db
from app.utils.auth import require_auth
from app.utils.tenant_refs import reject_foreign_refs
from app.models.asset import Visitor
from datetime import datetime, date

bp = Blueprint('visitors', __name__)


@bp.get('')
@require_auth(roles=['hr_admin', 'manager'])
def list_visitors():
    visit_date = request.args.get('date', str(date.today()))
    status = request.args.get('status')
    page = int(request.args.get('page', 1))

    q = Visitor.active().filter_by(tenant_id=g.tenant_id)
    if status:
        q = q.filter_by(status=status)
    p = q.order_by(Visitor.created_at.desc()).paginate(page=page, per_page=30)
    return {
        'visitors': [_fmt(v) for v in p.items],
        'total': p.total, 'page': p.page, 'pages': p.pages
    }


@bp.post('')
@require_auth()
def register_visitor():
    d = request.get_json()
    _ref_err = reject_foreign_refs(d, {"host_employee_id": "Employee"})
    if _ref_err:
        return _ref_err
    v = Visitor(
        tenant_id=g.tenant_id,
        visitor_number=_next_number(g.tenant_id),
        name=d['name'],
        company=d.get('company'),
        phone=d.get('phone'),
        email=d.get('email'),
        purpose=d.get('purpose'),
        host_employee_id=d.get('host_employee_id'),
        id_type=d.get('id_type'),
        id_number=d.get('id_number'),
        items_carried=d.get('items_carried'),
        vehicle_number=d.get('vehicle_number'),
        status='expected'
    )
    db.session.add(v)
    db.session.commit()
    return {'visitor': _fmt(v)}, 201


@bp.post('/<uuid:visitor_id>/checkin')
@require_auth()
def checkin_visitor(visitor_id):
    v = Visitor.active().filter_by(id=str(visitor_id), tenant_id=g.tenant_id).first_or_404()
    v.check_in_time = datetime.utcnow()
    v.status = 'checked_in'
    v.badge_number = request.get_json().get('badge_number')
    db.session.commit()
    return {'message': 'Visitor checked in', 'check_in_time': v.check_in_time.isoformat()}


@bp.post('/<uuid:visitor_id>/checkout')
@require_auth()
def checkout_visitor(visitor_id):
    v = Visitor.active().filter_by(id=str(visitor_id), tenant_id=g.tenant_id).first_or_404()
    v.check_out_time = datetime.utcnow()
    v.status = 'checked_out'
    db.session.commit()
    return {'message': 'Visitor checked out'}


def _next_number(tenant_id):
    count = Visitor.query.filter_by(tenant_id=tenant_id).count()
    return f'VIS-{count + 1:05d}'


def _fmt(v):
    return {
        'id': str(v.id),
        'visitor_number': v.visitor_number,
        'name': v.name,
        'company': v.company,
        'phone': v.phone,
        'purpose': v.purpose,
        'host_employee_id': str(v.host_employee_id) if v.host_employee_id else None,
        'status': v.status,
        'badge_number': v.badge_number,
        'check_in_time': v.check_in_time.isoformat() if v.check_in_time else None,
        'check_out_time': v.check_out_time.isoformat() if v.check_out_time else None,
        'created_at': v.created_at.isoformat() if v.created_at else None,
    }
