import uuid
from datetime import datetime, timezone, date, timedelta
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import (
    LeaveType, LeaveBalance, LeaveApplication, LeaveApplicationStatus,
    LeaveAccrualLog, CompOff, Employee, Holiday
)
from app.utils.auth import require_auth, log_action

leave_bp = Blueprint("leave", __name__)


def _count_leave_days(from_date: date, to_date: date, leave_type: LeaveType,
                       tenant_id: str, employee_id) -> float:
    """Count actual leave days respecting weekends and holidays if configured."""
    from app.models import Holiday
    holidays = {h.date for h in Holiday.query.filter(
        Holiday.tenant_id == tenant_id,
        Holiday.date >= from_date,
        Holiday.date <= to_date,
        Holiday.is_optional == False,
        Holiday.is_deleted == False
    ).all()}

    count = 0.0
    current = from_date
    while current <= to_date:
        weekday = current.weekday()
        is_weekend = weekday >= 5
        is_holiday = current in holidays
        if leave_type.count_weekends or not is_weekend:
            if leave_type.count_holidays or not is_holiday:
                count += 1.0
        current += timedelta(days=1)
    return count


@leave_bp.route("/types", methods=["GET"])
@require_auth()
def list_types():
    types = LeaveType.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).order_by(LeaveType.name).all()
    return jsonify({"leave_types": [t.to_dict() for t in types]})


@leave_bp.route("/types", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_type():
    data = request.get_json(silent=True) or {}
    lt = LeaveType(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=data.get("name", "").strip(),
        code=data.get("code", "").strip().upper(),
        description=data.get("description"),
        color=data.get("color", "#3b82f6"),
        accrual_type=data.get("accrual_type", "monthly"),
        accrual_days_per_period=float(data.get("accrual_days_per_period", 1.5)),
        max_balance=float(data.get("max_balance", 60)),
        max_carry_forward=float(data.get("max_carry_forward", 0)),
        min_days_per_application=float(data.get("min_days_per_application", 0.5)),
        max_days_per_application=float(data.get("max_days_per_application", 30)),
        notice_days_before=int(data.get("notice_days_before", 1)),
        allow_half_day=bool(data.get("allow_half_day", True)),
        allow_negative=bool(data.get("allow_negative", False)),
        is_paid=bool(data.get("is_paid", True)),
        is_encashable=bool(data.get("is_encashable", False)),
        requires_document=bool(data.get("requires_document", False)),
        document_required_after_days=int(data.get("document_required_after_days", 3)),
        sandwich_policy=bool(data.get("sandwich_policy", True)),
        count_weekends=bool(data.get("count_weekends", False)),
        count_holidays=bool(data.get("count_holidays", False)),
    )
    db.session.add(lt)
    db.session.commit()
    return jsonify({"leave_type": lt.to_dict()}), 201


@leave_bp.route("/balance", methods=["GET"])
@require_auth()
def get_balance():
    employee_id = request.args.get("employee_id") or str(g.employee.id)
    if g.role == "employee" and employee_id != str(g.employee.id):
        return jsonify({"error": "Access denied"}), 403
    year = int(request.args.get("year", datetime.now().year))

    balances = LeaveBalance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=employee_id, year=year, is_deleted=False
    ).all()

    result = []
    for bal in balances:
        lt = LeaveType.query.get(bal.leave_type_id)
        result.append({
            "leave_type_id": str(bal.leave_type_id),
            "leave_type": lt.name if lt else None,
            "code": lt.code if lt else None,
            "color": lt.color if lt else None,
            "year": bal.year,
            "opening": float(bal.opening_balance or 0),
            "credited": float(bal.credited or 0),
            "availed": float(bal.availed or 0),
            "pending": float(bal.pending or 0),
            "carry_forward": float(bal.carry_forward or 0),
            "balance": bal.balance,
            "is_paid": lt.is_paid if lt else True,
        })
    return jsonify({"balances": result, "year": year})


@leave_bp.route("/apply", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin"])
def apply_leave():
    from app.schemas.leave import LeaveApplicationSchema
    from app.schemas import validate_request

    data = request.get_json(silent=True) or {}
    validated, err = validate_request(LeaveApplicationSchema(), data)
    if err:
        return err

    emp = g.employee
    leave_type_id = validated["leave_type_id"]
    from_date = validated["from_date"]
    to_date = validated["to_date"]
    reason = validated["reason"]

    lt = LeaveType.query.filter_by(
        id=leave_type_id, tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).first()
    if not lt:
        return jsonify({"error": "Leave type not found"}), 404

    days = _count_leave_days(from_date, to_date, lt, g.tenant_id, emp.id)
    from_half = data.get("from_half")
    to_half = data.get("to_half")
    if from_half == "second":
        days -= 0.5
    if to_half == "first":
        days -= 0.5

    if days <= 0:
        return jsonify({"error": "Leave days cannot be zero or negative after applying policy"}), 400

    year = from_date.year
    balance = LeaveBalance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id,
        leave_type_id=leave_type_id, year=year, is_deleted=False
    ).first()

    if not lt.allow_negative and (not balance or balance.balance < days):
        return jsonify({
            "error": f"Insufficient leave balance. Available: {balance.balance if balance else 0}, Requested: {days}"
        }), 400

    application = LeaveApplication(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp.id,
        leave_type_id=leave_type_id,
        from_date=from_date,
        to_date=to_date,
        from_half=from_half,
        to_half=to_half,
        days_count=days,
        reason=reason,
        contact_during_leave=data.get("contact_during_leave"),
        status=LeaveApplicationStatus.PENDING,
    )
    db.session.add(application)

    if balance:
        balance.pending = float(balance.pending or 0) + days

    db.session.commit()
    log_action("apply_leave", "leave_application", application.id)
    return jsonify({
        "message": "Leave application submitted",
        "application": application.to_dict(),
        "days_requested": days,
    }), 201


@leave_bp.route("/applications", methods=["GET"])
@require_auth()
def list_applications():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    year = request.args.get("year")

    q = LeaveApplication.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)

    if g.role == "employee":
        q = q.filter_by(employee_id=g.employee.id)
    elif g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
        q = q.filter(LeaveApplication.employee_id.in_(team_ids))
    elif employee_id:
        q = q.filter_by(employee_id=employee_id)

    if status:
        q = q.filter_by(status=status)
    if year:
        q = q.filter(db.extract("year", LeaveApplication.from_date) == int(year))

    pagination = q.order_by(LeaveApplication.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    def _enrich(a):
        d = a.to_dict()
        d["start_date"] = d.get("from_date")
        d["end_date"] = d.get("to_date")
        d["days"] = d.get("days_count")
        if a.employee:
            d["employee_name"] = a.employee.full_name
            d["employee_number"] = a.employee.employee_number
        if a.leave_type:
            d["leave_type"] = a.leave_type.name
        return d

    items = [_enrich(a) for a in pagination.items]
    return jsonify({
        "applications": items,
        "leaves": items,
        "total": pagination.total,
        "page": page,
    })


@leave_bp.route("/applications/<app_id>/review", methods=["POST"])
@require_auth(roles=["hr_admin", "manager"])
def review_application(app_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    remarks = data.get("remarks", "")

    if action not in ("approve", "reject"):
        return jsonify({"error": "Action must be 'approve' or 'reject'"}), 400

    application = LeaveApplication.query.filter_by(
        id=app_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    if application.status != LeaveApplicationStatus.PENDING:
        return jsonify({"error": "Application is no longer pending"}), 409

    application.reviewed_by_id = g.employee.id
    application.reviewed_at = datetime.now(timezone.utc)
    application.review_remarks = remarks

    balance = LeaveBalance.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=application.employee_id,
        leave_type_id=application.leave_type_id,
        year=application.from_date.year,
        is_deleted=False
    ).first()

    if action == "approve":
        application.status = LeaveApplicationStatus.APPROVED
        if balance:
            balance.pending = max(0, float(balance.pending or 0) - float(application.days_count))
            balance.availed = float(balance.availed or 0) + float(application.days_count)
    else:
        application.status = LeaveApplicationStatus.REJECTED
        if balance:
            balance.pending = max(0, float(balance.pending or 0) - float(application.days_count))

    db.session.commit()
    log_action(f"leave_{action}", "leave_application", application.id)

    applicant = Employee.query.filter_by(id=application.employee_id, is_deleted=False).first()
    leave_type_obj = LeaveType.query.filter_by(id=application.leave_type_id).first()
    if applicant and applicant.work_email:
        from app.services.email_service import queue_email
        from app.models import Tenant
        tenant = Tenant.query.get(g.tenant_id)
        template = f"email/leave_{'approved' if action == 'approve' else 'rejected'}.html"
        queue_email(
            applicant.work_email,
            f"Leave {'Approved' if action == 'approve' else 'Not Approved'} — {leave_type_obj.name if leave_type_obj else 'Leave'}",
            template,
            {
                'employee_name': applicant.full_name,
                'leave_type': leave_type_obj.name if leave_type_obj else 'Leave',
                'from_date': str(application.from_date),
                'to_date': str(application.to_date),
                'days_count': application.days_count,
                'remarks': remarks,
                'reviewed_by': g.employee.full_name,
                'company_name': tenant.name if tenant else '',
            },
        )

    return jsonify({"message": f"Leave {action}d", "application": application.to_dict()})


@leave_bp.route("/pending-approvals", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def pending_approvals():
    q = LeaveApplication.query.filter_by(
        tenant_id=g.tenant_id, status=LeaveApplicationStatus.PENDING, is_deleted=False
    )
    if g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
        q = q.filter(LeaveApplication.employee_id.in_(team_ids))
    apps = q.order_by(LeaveApplication.created_at).all()
    return jsonify({"pending": [a.to_dict() for a in apps]})


@leave_bp.route("/accrue", methods=["POST"])
@require_auth(roles=["hr_admin"])
def accrue_leave():
    """Manually trigger monthly leave accrual for all active employees."""
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month

    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).all()
    leave_types = LeaveType.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True, accrual_type="monthly"
    ).all()

    accrued_count = 0
    for emp in employees:
        for lt in leave_types:
            balance = LeaveBalance.query.filter_by(
                tenant_id=g.tenant_id,
                employee_id=emp.id,
                leave_type_id=lt.id,
                year=year,
                is_deleted=False
            ).first()
            if not balance:
                balance = LeaveBalance(
                    id=uuid.uuid4(),
                    tenant_id=g.tenant_id,
                    employee_id=emp.id,
                    leave_type_id=lt.id,
                    year=year,
                )
                db.session.add(balance)

            days = float(lt.accrual_days_per_period or 0)
            new_balance = float(balance.credited or 0) + days
            if lt.max_balance:
                new_balance = min(new_balance, float(lt.max_balance))
            balance.credited = new_balance

            log_entry = LeaveAccrualLog(
                id=uuid.uuid4(),
                tenant_id=g.tenant_id,
                employee_id=emp.id,
                leave_type_id=lt.id,
                year=year,
                month=month,
                days_accrued=days,
                reason="monthly_accrual",
            )
            db.session.add(log_entry)
            accrued_count += 1

    db.session.commit()
    return jsonify({"message": "Accrual completed", "records_updated": accrued_count})


@leave_bp.route("/comp-off", methods=["GET"])
@require_auth()
def list_comp_off():
    year = int(request.args.get("year", datetime.utcnow().year))
    comps = CompOff.query.filter(
        CompOff.tenant_id == g.tenant_id,
        CompOff.employee_id == g.employee.id,
        CompOff.is_deleted == False,
    ).order_by(CompOff.created_at.desc()).all()

    balances = LeaveBalance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=g.employee.id, is_deleted=False
    ).all()
    balance_map = {}
    for b in balances:
        lt = LeaveType.query.get(b.leave_type_id)
        if lt:
            balance_map[lt.name] = float(b.balance)

    return jsonify({
        "records": [{
            "id": str(c.id),
            "name": g.employee.full_name,
            "type": "Week Off" if not c.reason else c.reason.split()[0],
            "comp_off_date": c.worked_date.isoformat() if c.worked_date else None,
            "remark": c.reason,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "approved_on": c.approved_at.isoformat() if c.approved_at else None,
            "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
            "expired": bool(c.expiry_date and c.expiry_date < date.today()),
            "availed_date": None,
            "status": c.status,
        } for c in comps],
        "balance": balance_map,
    })


@leave_bp.route("/comp-off", methods=["POST"])
@require_auth(roles=["employee", "manager"])
def apply_comp_off():
    data = request.get_json(silent=True) or {}
    worked_on = data.get("worked_on") or data.get("worked_date")
    comp = CompOff(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        worked_date=datetime.strptime(worked_on, "%Y-%m-%d").date() if worked_on else date.today(),
        reason=data.get("reason", "").strip(),
        days_earned=float(data.get("days_earned", 1.0)),
        status="pending",
    )
    db.session.add(comp)
    db.session.commit()
    return jsonify({"message": "Comp-off request submitted", "id": str(comp.id)}), 201


@leave_bp.route("/summary", methods=["GET"])
@require_auth()
def leave_summary():
    balances = LeaveBalance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=g.employee.id, is_deleted=False
    ).all()
    apps = LeaveApplication.query.filter(
        LeaveApplication.tenant_id == g.tenant_id,
        LeaveApplication.employee_id == g.employee.id,
        LeaveApplication.is_deleted == False,
    ).order_by(LeaveApplication.created_at.desc()).all()

    accruals = LeaveAccrualLog.query.filter(
        LeaveAccrualLog.tenant_id == g.tenant_id,
        LeaveAccrualLog.employee_id == g.employee.id,
        LeaveAccrualLog.is_deleted == False,
    ).order_by(LeaveAccrualLog.created_at.desc()).all()

    summary = []
    # Add accrual entries
    for acc in accruals:
        lt = LeaveType.query.get(acc.leave_type_id)
        summary.append({
            "leave_type": lt.name if lt else "Unknown",
            "date": acc.period_start.isoformat() if acc.period_start else (acc.created_at.date().isoformat() if acc.created_at else None),
            "description": "Entitlement",
            "allotted": float(acc.days_accrued),
            "taken": 0.0,
        })
    # Add leave availed entries
    for app in apps:
        if app.status in (LeaveApplicationStatus.APPROVED, "approved"):
            lt = LeaveType.query.get(app.leave_type_id)
            summary.append({
                "leave_type": lt.name if lt else "Unknown",
                "date": app.from_date.isoformat() if app.from_date else None,
                "description": "Leave Availed",
                "allotted": 0.0,
                "taken": float(app.days_count) if app.days_count else 0.0,
            })

    balance_map = {}
    for b in balances:
        lt = LeaveType.query.get(b.leave_type_id)
        if lt:
            balance_map[lt.name] = float(b.balance)

    return jsonify({"summary": summary, "balance": balance_map})


@leave_bp.route("/team-calendar", methods=["GET"])
@require_auth(roles=["employee", "manager", "hr_admin", "payroll_admin"])
def team_calendar():
    """Return approved/pending leave applications for all visible employees in a given month."""
    month_str = request.args.get("month", date.today().strftime("%Y-%m"))
    try:
        period_start = date.fromisoformat(f"{month_str}-01")
    except ValueError:
        return jsonify({"error": "Invalid month format — expected YYYY-MM"}), 400

    # Last day of the month
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1, day=1) - timedelta(days=1)

    # Determine which employees are visible
    if g.role in ("hr_admin", "payroll_admin"):
        scope = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).all()
    elif g.role == "manager":
        scope = Employee.query.filter_by(
            tenant_id=g.tenant_id,
            reporting_manager_id=g.employee.id,
            is_deleted=False,
        ).all()
    else:
        # Employee: only their own leaves (still useful for personal calendar)
        scope = [g.employee]

    scope_ids = [e.id for e in scope]
    emp_map = {str(e.id): e for e in scope}

    if not scope_ids:
        return jsonify({"month": month_str, "leaves": [], "employees": []})

    apps = LeaveApplication.query.filter(
        LeaveApplication.tenant_id == g.tenant_id,
        LeaveApplication.employee_id.in_(scope_ids),
        LeaveApplication.is_deleted == False,
        LeaveApplication.from_date <= period_end,
        LeaveApplication.to_date >= period_start,
        LeaveApplication.status.in_(
            [LeaveApplicationStatus.APPROVED.value, LeaveApplicationStatus.PENDING.value]
            if hasattr(LeaveApplicationStatus.APPROVED, "value")
            else ["approved", "pending"]
        ),
    ).all()

    leave_entries = []
    for app in apps:
        emp = emp_map.get(str(app.employee_id))
        lt = LeaveType.query.get(app.leave_type_id)
        leave_entries.append({
            "id": str(app.id),
            "employee_id": str(app.employee_id),
            "employee_name": emp.full_name if emp else "Unknown",
            "employee_number": emp.employee_number if emp else "",
            "leave_type": lt.name if lt else "Leave",
            "from_date": app.from_date.isoformat(),
            "to_date": app.to_date.isoformat(),
            "days": float(app.days_count) if app.days_count else 0,
            "status": app.status.value if hasattr(app.status, "value") else str(app.status),
            "reason": app.reason or "",
        })

    employees_out = [
        {"id": str(e.id), "name": e.full_name, "number": e.employee_number}
        for e in scope
    ]
    return jsonify({"month": month_str, "leaves": leave_entries, "employees": employees_out})
