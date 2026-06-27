from flask import Blueprint, request, g
from app.extensions import db
from app.utils.auth import require_auth, log_action
from app.models.expense import Asset, AssetCategory, AssetAssignment
from datetime import datetime

bp = Blueprint('assets', __name__)


@bp.get('')
@require_auth()
def list_assets():
    status = request.args.get('status')
    category = request.args.get('category_id')
    page = int(request.args.get('page', 1))

    q = Asset.active().filter_by(tenant_id=g.tenant_id)
    if status:
        q = q.filter_by(status=status)
    if category:
        q = q.filter_by(category_id=category)

    p = q.paginate(page=page, per_page=25)
    return {'assets': [_fmt(a) for a in p.items], 'total': p.total, 'page': p.page, 'pages': p.pages}


@bp.post('')
@require_auth(roles=['hr_admin'])
def create_asset():
    d = request.get_json()
    count = Asset.query.filter_by(tenant_id=g.tenant_id).count()
    a = Asset(
        tenant_id=g.tenant_id,
        asset_code=d.get('asset_code') or f'ASSET-{count+1:04d}',
        name=d['name'],
        category_id=d.get('category_id'),
        brand=d.get('brand'),
        model=d.get('model'),
        serial_number=d.get('serial_number'),
        purchase_date=d.get('purchase_date'),
        purchase_cost=d.get('purchase_cost'),
        current_value=d.get('current_value') or d.get('purchase_cost'),
        location=d.get('location'),
        warranty_expiry=d.get('warranty_expiry'),
        notes=d.get('notes'),
        status='available',
    )
    db.session.add(a)
    log_action(g.tenant_id, g.employee.id, 'asset_created', 'asset', None)
    db.session.commit()
    return {'asset': _fmt(a)}, 201


@bp.post('/<uuid:asset_id>/assign')
@require_auth(roles=['hr_admin'])
def assign_asset(asset_id):
    a = Asset.active().filter_by(id=str(asset_id), tenant_id=g.tenant_id).first_or_404()
    if a.status == 'assigned':
        return {'error': 'Asset already assigned'}, 400

    d = request.get_json()
    assignment = AssetAssignment(
        tenant_id=g.tenant_id,
        asset_id=str(asset_id),
        employee_id=d['employee_id'],
        assigned_by_id=str(g.employee.id),
        assigned_at=datetime.utcnow(),
        condition_on_assign=d.get('condition', 'good'),
    )
    db.session.add(assignment)
    a.status = 'assigned'
    a.assigned_to_id = d['employee_id']
    a.assigned_at = datetime.utcnow()

    log_action(g.tenant_id, g.employee.id, 'asset_assigned', 'asset', str(asset_id))
    db.session.commit()
    return {'message': 'Asset assigned', 'assignment_id': str(assignment.id)}


@bp.post('/<uuid:asset_id>/return')
@require_auth(roles=['hr_admin'])
def return_asset(asset_id):
    a = Asset.active().filter_by(id=str(asset_id), tenant_id=g.tenant_id).first_or_404()
    d = request.get_json() or {}

    active = AssetAssignment.query.filter_by(
        asset_id=str(asset_id), tenant_id=g.tenant_id
    ).filter(AssetAssignment.returned_at.is_(None)).first()
    if active:
        active.returned_at = datetime.utcnow()
        active.condition_on_return = d.get('condition')
        active.return_notes = d.get('notes')

    a.status = 'available'
    a.assigned_to_id = None

    log_action(g.tenant_id, g.employee.id, 'asset_returned', 'asset', str(asset_id))
    db.session.commit()
    return {'message': 'Asset returned'}


@bp.get('/my')
@require_auth()
def my_assets():
    assets = Asset.active().filter_by(tenant_id=g.tenant_id, assigned_to_id=str(g.employee.id)).all()
    return {'assets': [_fmt(a) for a in assets]}


@bp.get('/categories')
@require_auth()
def list_categories():
    cats = AssetCategory.active().filter_by(tenant_id=g.tenant_id).all()
    return {'categories': [{'id': str(c.id), 'name': c.name, 'code': c.code} for c in cats]}


def _fmt(a):
    return {
        'id': str(a.id),
        'asset_code': a.asset_code,
        'name': a.name,
        'category_id': str(a.category_id) if a.category_id else None,
        'brand': a.brand,
        'model': a.model,
        'serial_number': a.serial_number,
        'purchase_date': str(a.purchase_date) if a.purchase_date else None,
        'purchase_cost': float(a.purchase_cost) if a.purchase_cost else None,
        'current_value': float(a.current_value) if a.current_value else None,
        'status': a.status,
        'location': a.location,
        'assigned_to_id': str(a.assigned_to_id) if a.assigned_to_id else None,
        'warranty_expiry': str(a.warranty_expiry) if a.warranty_expiry else None,
    }
