from flask import Blueprint, request, g
from app.extensions import db
from app.utils.auth import require_auth, log_action
from app.models.asset import Timesheet, TimesheetEntry
from datetime import date, timedelta

bp = Blueprint('timesheets', __name__)


@bp.get('')
@require_auth()
def list_timesheets():
    q = Timesheet.active().filter_by(tenant_id=g.tenant_id)
    if g.role == 'employee':
        q = q.filter_by(employee_id=str(g.employee.id))
    sheets = q.order_by(Timesheet.week_start.desc()).limit(20).all()
    return {'timesheets': [_fmt(t) for t in sheets]}


@bp.post('')
@require_auth()
def create_timesheet():
    d = request.get_json()
    week_start = date.fromisoformat(d['week_start'])
    week_end = week_start + timedelta(days=6)

    existing = Timesheet.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=str(g.employee.id),
        week_start=week_start
    ).first()
    if existing:
        return {'error': 'Timesheet for this week already exists', 'id': str(existing.id)}, 409

    ts = Timesheet(
        tenant_id=g.tenant_id,
        employee_id=str(g.employee.id),
        week_start=week_start,
        week_end=week_end,
        status='draft',
        total_hours=0,
        billable_hours=0
    )
    db.session.add(ts)
    db.session.flush()

    total = 0
    billable = 0
    for entry_data in d.get('entries', []):
        hours = float(entry_data.get('hours', 0))
        entry = TimesheetEntry(
            tenant_id=g.tenant_id,
            timesheet_id=str(ts.id),
            date=entry_data['date'],
            project=entry_data.get('project'),
            task=entry_data.get('task'),
            hours=hours,
            billable=entry_data.get('billable', True),
            description=entry_data.get('description')
        )
        db.session.add(entry)
        total += hours
        if entry_data.get('billable', True):
            billable += hours

    ts.total_hours = total
    ts.billable_hours = billable
    db.session.commit()
    return {'timesheet': _fmt(ts)}, 201


@bp.post('/<uuid:ts_id>/submit')
@require_auth()
def submit_timesheet(ts_id):
    from datetime import datetime
    ts = Timesheet.active().filter_by(
        id=str(ts_id), tenant_id=g.tenant_id, employee_id=str(g.employee.id)
    ).first_or_404()

    if ts.status not in ('draft',):
        return {'error': 'Only draft timesheets can be submitted'}, 400
    ts.status = 'submitted'
    ts.submitted_at = datetime.utcnow()
    log_action(g.tenant_id, g.employee.id, 'timesheet_submitted', 'timesheet', str(ts_id))
    db.session.commit()
    return {'message': 'Timesheet submitted'}


@bp.post('/<uuid:ts_id>/approve')
@require_auth(roles=['manager', 'hr_admin'])
def approve_timesheet(ts_id):
    from datetime import datetime
    ts = Timesheet.active().filter_by(id=str(ts_id), tenant_id=g.tenant_id).first_or_404()
    d = request.get_json() or {}
    action = d.get('action', 'approve')

    if action == 'approve':
        ts.status = 'approved'
        ts.approved_by_id = str(g.employee.id)
        ts.approved_at = datetime.utcnow()
    else:
        ts.status = 'rejected'
        ts.remarks = d.get('remarks')

    log_action(g.tenant_id, g.employee.id, f'timesheet_{action}d', 'timesheet', str(ts_id))
    db.session.commit()
    return {'message': f'Timesheet {action}d'}


def _fmt(ts):
    return {
        'id': str(ts.id),
        'employee_id': str(ts.employee_id),
        'week_start': str(ts.week_start),
        'week_end': str(ts.week_end),
        'status': ts.status,
        'total_hours': float(ts.total_hours or 0),
        'billable_hours': float(ts.billable_hours or 0),
        'submitted_at': ts.submitted_at.isoformat() if ts.submitted_at else None,
        'approved_at': ts.approved_at.isoformat() if ts.approved_at else None,
        'entries': [
            {
                'id': str(e.id),
                'date': str(e.date),
                'project': e.project,
                'task': e.task,
                'hours': float(e.hours),
                'billable': e.billable,
                'description': e.description,
            }
            for e in (ts.entries or [])
        ]
    }
