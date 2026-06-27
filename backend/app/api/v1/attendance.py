import uuid
from datetime import datetime, timezone, date, timedelta
from flask import Blueprint, request, jsonify, g
from sqlalchemy import and_
from app.extensions import db
from app.models import (
    Attendance, AttendanceStatus, AttendanceSource,
    AttendanceRegularization, Shift, EmployeeShift,
    Holiday, HolidayType, Roster, Employee
)
from app.utils.auth import require_auth, log_action

attendance_bp = Blueprint("attendance", __name__)


def _get_employee_shift(employee_id, date_val) -> Shift:
    es = EmployeeShift.query.filter(
        EmployeeShift.employee_id == employee_id,
        EmployeeShift.effective_from <= date_val,
        db.or_(EmployeeShift.effective_to.is_(None), EmployeeShift.effective_to >= date_val),
        EmployeeShift.is_deleted == False
    ).order_by(EmployeeShift.effective_from.desc()).first()
    return es.shift if es else None


@attendance_bp.route("/checkin", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin", "payroll_admin"])
def checkin():
    emp = g.employee
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    existing = Attendance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id, date=today, is_deleted=False
    ).first()

    if existing and existing.check_in:
        return jsonify({"error": "Already checked in today"}), 409

    data = request.get_json(silent=True) or {}
    from app.schemas.attendance import AttendanceCheckinSchema
    from app.schemas import validate_request
    validated, err = validate_request(AttendanceCheckinSchema(), data)
    if err:
        return err
    lat = validated["lat"]
    lng = validated["lng"]
    source = validated["source"]
    photo_url = validated["photo_url"]

    shift = _get_employee_shift(emp.id, today)

    if existing:
        existing.check_in = now
        existing.check_in_lat = str(lat) if lat else None
        existing.check_in_lng = str(lng) if lng else None
        existing.check_in_source = source
        existing.check_in_photo_url = photo_url
        existing.shift_id = shift.id if shift else None
        rec = existing
    else:
        rec = Attendance(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            employee_id=emp.id,
            date=today,
            check_in=now,
            check_in_source=source,
            check_in_lat=str(lat) if lat else None,
            check_in_lng=str(lng) if lng else None,
            check_in_photo_url=photo_url,
            shift_id=shift.id if shift else None,
            status=AttendanceStatus.PRESENT,
        )
        if shift:
            scheduled_in = datetime.combine(today, shift.start_time).replace(tzinfo=timezone.utc)
            late_mins = max(0, int((now - scheduled_in).total_seconds() / 60) - shift.grace_in_minutes)
            rec.late_minutes = late_mins
            if late_mins > 0:
                rec.status = AttendanceStatus.LATE
        db.session.add(rec)

    db.session.commit()
    return jsonify({
        "message": "Check-in recorded",
        "check_in": now.isoformat(),
        "status": rec.status.value,
    })


@attendance_bp.route("/checkout", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin", "payroll_admin"])
def checkout():
    emp = g.employee
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    rec = Attendance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id, date=today, is_deleted=False
    ).first()

    if not rec or not rec.check_in:
        return jsonify({"error": "No check-in found for today"}), 400
    if rec.check_out:
        return jsonify({"error": "Already checked out today"}), 409

    data = request.get_json(silent=True) or {}
    rec.check_out = now
    rec.check_out_source = data.get("source", AttendanceSource.WEB.value)
    rec.check_out_lat = str(data.get("lat")) if data.get("lat") else None
    rec.check_out_lng = str(data.get("lng")) if data.get("lng") else None
    rec.check_out_photo_url = data.get("photo_url")

    check_in_dt = rec.check_in if rec.check_in.tzinfo else rec.check_in.replace(tzinfo=timezone.utc)
    hours = (now - check_in_dt).total_seconds() / 3600
    rec.working_hours = round(hours, 2)

    shift = rec.shift if rec.shift_id else None
    if shift:
        scheduled_out = datetime.combine(today, shift.end_time).replace(tzinfo=timezone.utc)
        early_mins = max(0, int((scheduled_out - now).total_seconds() / 60))
        rec.early_exit_minutes = early_mins
        if hours >= float(shift.min_hours):
            rec.status = AttendanceStatus.PRESENT
        elif hours >= float(shift.half_day_hours):
            rec.status = AttendanceStatus.HALF_DAY
        else:
            rec.status = AttendanceStatus.PRESENT
        if hours > float(shift.min_hours):
            rec.overtime_hours = round(hours - float(shift.min_hours), 2)

    db.session.commit()
    return jsonify({
        "message": "Check-out recorded",
        "check_out": now.isoformat(),
        "working_hours": float(rec.working_hours or 0),
    })


@attendance_bp.route("/today", methods=["GET"])
@require_auth()
def today_status():
    emp = g.employee
    today = datetime.now(timezone.utc).date()
    rec = Attendance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id, date=today, is_deleted=False
    ).first()
    shift = _get_employee_shift(emp.id, today)
    return jsonify({
        "date": today.isoformat(),
        "status": rec.status.value if rec else "not_checked_in",
        "check_in": rec.check_in.isoformat() if rec and rec.check_in else None,
        "check_out": rec.check_out.isoformat() if rec and rec.check_out else None,
        "working_hours": float(rec.working_hours or 0) if rec else 0,
        "late_minutes": rec.late_minutes if rec else 0,
        "shift": {
            "name": shift.name,
            "start": shift.start_time.strftime("%H:%M"),
            "end": shift.end_time.strftime("%H:%M"),
        } if shift else None,
    })


@attendance_bp.route("/monthly", methods=["GET"])
@require_auth()
def monthly():
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    employee_id = request.args.get("employee_id")

    if g.role == "employee":
        employee_id = str(g.employee.id)
    elif not employee_id:
        employee_id = str(g.employee.id)

    if g.role == "manager":
        emp = Employee.query.filter_by(
            id=employee_id, tenant_id=g.tenant_id, reporting_manager_id=g.employee.id
        ).first()
        if not emp:
            employee_id = str(g.employee.id)

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    records = Attendance.query.filter(
        Attendance.tenant_id == g.tenant_id,
        Attendance.employee_id == employee_id,
        Attendance.date >= start,
        Attendance.date <= end,
        Attendance.is_deleted == False
    ).order_by(Attendance.date).all()

    holidays = Holiday.query.filter(
        Holiday.tenant_id == g.tenant_id,
        Holiday.year == year,
        Holiday.date >= start,
        Holiday.date <= end,
        Holiday.is_deleted == False
    ).all()
    holiday_dates = {h.date: h.name for h in holidays}

    summary = {
        "present": 0, "absent": 0, "late": 0, "half_day": 0,
        "on_leave": 0, "holiday": 0, "weekly_off": 0, "wfh": 0,
    }
    days = []
    for rec in records:
        status = rec.status.value if rec.status else "unknown"
        summary[status] = summary.get(status, 0) + 1
        days.append({
            "date": rec.date.isoformat(),
            "status": status,
            "check_in": rec.check_in.isoformat() if rec.check_in else None,
            "check_out": rec.check_out.isoformat() if rec.check_out else None,
            "working_hours": float(rec.working_hours or 0),
            "late_minutes": rec.late_minutes or 0,
            "overtime_hours": float(rec.overtime_hours or 0),
            "is_regularized": rec.is_regularized,
            "is_holiday": rec.date in holiday_dates,
            "holiday_name": holiday_dates.get(rec.date),
        })

    return jsonify({
        "year": year,
        "month": month,
        "employee_id": employee_id,
        "summary": summary,
        "records": days,
    })


@attendance_bp.route("/wfh", methods=["POST"])
@require_auth()
def apply_wfh():
    data = request.get_json(silent=True) or {}
    req_date_str = data.get("date") or data.get("wfh_date")
    if not req_date_str:
        return jsonify({"error": "date is required"}), 400
    req_date = datetime.strptime(req_date_str, "%Y-%m-%d").date()
    reason = data.get("reason", "").strip()

    existing = Attendance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=g.employee.id,
        date=req_date, is_deleted=False
    ).first()
    if existing:
        existing.status = AttendanceStatus.WORK_FROM_HOME
        existing.notes = reason
    else:
        att = Attendance(
            id=uuid.uuid4(), tenant_id=g.tenant_id,
            employee_id=g.employee.id, date=req_date,
            status=AttendanceStatus.WORK_FROM_HOME,
            notes=reason,
        )
        db.session.add(att)
    db.session.commit()
    return jsonify({"message": "WFH request submitted"}), 201


@attendance_bp.route("/regularizations", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin"])
def regularize_alias():
    """POST alias matching frontend URL /attendance/regularizations."""
    return regularize()


@attendance_bp.route("/regularize", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin"])
def regularize():
    data = request.get_json(silent=True) or {}
    emp = g.employee
    req_date = datetime.strptime(data.get("date"), "%Y-%m-%d").date()
    reason = data.get("reason", "").strip()
    if not reason:
        return jsonify({"error": "Reason is required"}), 400

    reg = AttendanceRegularization(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp.id,
        date=req_date,
        reason=reason,
        requested_check_in=datetime.fromisoformat(data["check_in"]) if data.get("check_in") else None,
        requested_check_out=datetime.fromisoformat(data["check_out"]) if data.get("check_out") else None,
        status="pending",
    )
    db.session.add(reg)
    db.session.commit()
    return jsonify({"message": "Regularization request submitted", "id": str(reg.id)}), 201


@attendance_bp.route("/regularizations", methods=["GET"])
@require_auth()
def my_regularizations():
    """Employee-facing: list own regularization requests."""
    regs = AttendanceRegularization.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).order_by(AttendanceRegularization.created_at.desc()).limit(100).all()
    result = []
    for r in regs:
        att = Attendance.query.filter_by(
            tenant_id=g.tenant_id, employee_id=g.employee.id,
            date=r.date, is_deleted=False
        ).first()
        roster_in = None
        roster_out = None
        if att and att.shift_id:
            shift = Shift.query.get(att.shift_id)
            if shift:
                roster_in = str(shift.start_time) if shift.start_time else None
                roster_out = str(shift.end_time) if shift.end_time else None
        result.append({
            "id": str(r.id),
            "from_date": r.date.isoformat() if r.date else None,
            "to_date": r.date.isoformat() if r.date else None,
            "roster_in": roster_in,
            "roster_out": roster_out,
            "first_half": att.first_half_status if att and hasattr(att, "first_half_status") else None,
            "second_half": att.second_half_status if att and hasattr(att, "second_half_status") else None,
            "emp_check_in": r.requested_check_in.strftime("%I:%M %p") if r.requested_check_in else None,
            "emp_check_out": r.requested_check_out.strftime("%I:%M %p") if r.requested_check_out else None,
            "reason": r.reason,
            "count_weekoff_holiday": "No",
            "status": r.status,
        })
    return jsonify({"regularizations": result})


@attendance_bp.route("/roster", methods=["GET"])
@require_auth()
def my_roster():
    """Employee-facing: own shift roster for a given month."""
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    roster = Roster.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        year=year,
        month=month,
        is_deleted=False,
    ).first()
    schedule = {}
    if roster and roster.schedule:
        raw = roster.schedule
        for day_key, val in raw.items():
            if isinstance(val, dict):
                schedule[str(day_key)] = val
            elif isinstance(val, str):
                shift = Shift.query.filter_by(id=val, tenant_id=g.tenant_id, is_deleted=False).first()
                if shift:
                    schedule[str(day_key)] = {
                        "type": "working",
                        "shift_name": shift.name,
                        "start_time": str(shift.start_time) if shift.start_time else None,
                        "end_time": str(shift.end_time) if shift.end_time else None,
                    }
                else:
                    schedule[str(day_key)] = {"type": val}
            else:
                schedule[str(day_key)] = {"type": str(val)}
    holidays = Holiday.query.filter_by(
        tenant_id=g.tenant_id, year=year, is_deleted=False
    ).filter(Holiday.date >= date(year, month, 1)).filter(
        Holiday.date <= date(year, month, 28 if month == 2 else (30 if month in [4,6,9,11] else 31))
    ).all()
    holiday_days = {h.date.day: h.name for h in holidays}
    return jsonify({
        "year": year,
        "month": month,
        "schedule": schedule,
        "holidays": holiday_days,
    })


@attendance_bp.route("/wfh-requests", methods=["GET"])
@require_auth()
def wfh_requests():
    """Employee's own WFH request history."""
    q = Attendance.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=str(g.employee.id),
        status=AttendanceStatus.WORK_FROM_HOME,
        is_deleted=False,
    ).order_by(Attendance.date.desc()).limit(60)
    records = q.all()
    return jsonify({
        "records": [
            {
                "id": str(r.id),
                "date": r.date.isoformat() if r.date else None,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "notes": r.notes,
                "check_in": r.check_in.isoformat() if r.check_in else None,
                "check_out": r.check_out.isoformat() if r.check_out else None,
            }
            for r in records
        ]
    })


@attendance_bp.route("/admin/summary", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def admin_summary():
    """Admin: attendance counts for a given date."""
    date_str = request.args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400

    q = Attendance.query.filter_by(tenant_id=g.tenant_id, date=target_date, is_deleted=False)
    if g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
        q = q.filter(Attendance.employee_id.in_(team_ids))

    records = q.all()
    summary = {"present": 0, "absent": 0, "late": 0, "wfh": 0, "on_leave": 0, "total": len(records)}
    for r in records:
        s = r.status.value if hasattr(r.status, "value") else str(r.status)
        if s in ("present", "regularized", "on_duty", "comp_off"):
            summary["present"] += 1
        elif s == "absent":
            summary["absent"] += 1
        elif s in ("late", "half_day"):
            summary["late"] += 1
        elif s == "work_from_home":
            summary["wfh"] += 1
        elif s == "on_leave":
            summary["on_leave"] += 1
    return jsonify({"date": date_str, "summary": summary})


@attendance_bp.route("/admin/daily", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def admin_daily():
    """Admin: full attendance list for a date."""
    date_str = request.args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400

    q = Attendance.query.filter_by(tenant_id=g.tenant_id, date=target_date, is_deleted=False)
    if g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
        q = q.filter(Attendance.employee_id.in_(team_ids))

    records = q.order_by(Attendance.check_in).all()
    result = []
    for r in records:
        emp = Employee.query.get(r.employee_id)
        result.append({
            "employee_id": str(r.employee_id),
            "employee_name": emp.full_name if emp else "-",
            "employee_number": emp.employee_number if emp else "-",
            "date": r.date.isoformat(),
            "check_in": r.check_in.isoformat() if r.check_in else None,
            "check_out": r.check_out.isoformat() if r.check_out else None,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "total_hours": float(r.total_hours or 0),
            "is_regularized": r.is_regularized,
        })
    return jsonify({"date": date_str, "records": result, "total": len(result)})


@attendance_bp.route("/admin/export", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def admin_export():
    """Export attendance as CSV for a date range."""
    import csv, io
    from flask import Response
    date_str = request.args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    month = request.args.get("month")
    year_arg = request.args.get("year")

    q = Attendance.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if month and year_arg:
        q = q.filter(
            db.extract("year", Attendance.date) == int(year_arg),
            db.extract("month", Attendance.date) == int(month),
        )
    else:
        try:
            q = q.filter_by(date=date.fromisoformat(date_str))
        except ValueError:
            pass

    records = q.order_by(Attendance.date, Attendance.employee_id).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Employee Number", "Employee Name", "Date", "Check In", "Check Out", "Status", "Hours", "Regularized"])
    for r in records:
        emp = Employee.query.get(r.employee_id)
        writer.writerow([
            emp.employee_number if emp else "-",
            emp.full_name if emp else "-",
            r.date.isoformat() if r.date else "",
            r.check_in.strftime("%H:%M") if r.check_in else "",
            r.check_out.strftime("%H:%M") if r.check_out else "",
            r.status.value if hasattr(r.status, "value") else str(r.status),
            float(r.total_hours or 0),
            "Yes" if r.is_regularized else "No",
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance_export.csv"},
    )


@attendance_bp.route("/team", methods=["GET"])
@require_auth()
def team_attendance():
    """Manager/HR: team attendance for a date."""
    date_str = request.args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400

    if g.role == "employee":
        team_ids = [str(g.employee.id)]
    elif g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
    else:
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, is_deleted=False, is_active=True
        ).limit(50).all()]

    records = Attendance.query.filter(
        Attendance.tenant_id == g.tenant_id,
        Attendance.date == target_date,
        Attendance.employee_id.in_(team_ids),
        Attendance.is_deleted == False,
    ).all()
    att_map = {str(r.employee_id): r for r in records}
    result = []
    for emp_id in team_ids:
        emp = Employee.query.get(emp_id)
        if not emp:
            continue
        r = att_map.get(emp_id)
        result.append({
            "employee_id": emp_id,
            "employee_name": emp.full_name,
            "employee_number": emp.employee_number,
            "status": (r.status.value if hasattr(r.status, "value") else str(r.status)) if r else "absent",
            "check_in": r.check_in.isoformat() if r and r.check_in else None,
            "check_out": r.check_out.isoformat() if r and r.check_out else None,
            "total_hours": float(r.total_hours or 0) if r else 0,
        })
    return jsonify({"date": date_str, "records": result, "total": len(result)})


@attendance_bp.route("/regularize/pending", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def pending_regularizations():
    q = AttendanceRegularization.query.filter_by(
        tenant_id=g.tenant_id, status="pending", is_deleted=False
    )
    if g.role == "manager":
        from app.models import Employee as Emp
        team_ids = [str(e.id) for e in Emp.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
        q = q.filter(AttendanceRegularization.employee_id.in_(team_ids))
    regs = q.order_by(AttendanceRegularization.created_at.desc()).all()
    return jsonify({"regularizations": [r.to_dict() for r in regs]})


@attendance_bp.route("/regularize/<reg_id>/approve", methods=["POST"])
@require_auth(roles=["hr_admin", "manager"])
def approve_regularization(reg_id):
    data = request.get_json(silent=True) or {}
    reg = AttendanceRegularization.query.filter_by(
        id=reg_id, tenant_id=g.tenant_id, status="pending", is_deleted=False
    ).first_or_404()
    action = data.get("action", "approve")
    reg.reviewed_by_id = g.employee.id
    reg.reviewed_at = datetime.now(timezone.utc)
    reg.review_remarks = data.get("remarks", "")
    if action == "approve":
        reg.status = "approved"
        att = Attendance.query.filter_by(
            tenant_id=g.tenant_id, employee_id=reg.employee_id, date=reg.date, is_deleted=False
        ).first()
        if att:
            if reg.requested_check_in:
                att.check_in = reg.requested_check_in
            if reg.requested_check_out:
                att.check_out = reg.requested_check_out
            att.is_regularized = True
            att.regularization_id = reg.id
            att.status = AttendanceStatus.REGULARIZED
        else:
            att = Attendance(
                id=uuid.uuid4(),
                tenant_id=g.tenant_id,
                employee_id=reg.employee_id,
                date=reg.date,
                check_in=reg.requested_check_in,
                check_out=reg.requested_check_out,
                status=AttendanceStatus.REGULARIZED,
                is_regularized=True,
                regularization_id=reg.id,
            )
            db.session.add(att)
    else:
        reg.status = "rejected"
    db.session.commit()
    return jsonify({"message": f"Regularization {action}d"})


@attendance_bp.route("/holidays", methods=["GET"])
@require_auth()
def list_holidays():
    year = int(request.args.get("year", datetime.now().year))
    holidays = Holiday.query.filter_by(
        tenant_id=g.tenant_id, year=year, is_deleted=False
    ).order_by(Holiday.date).all()
    return jsonify({"holidays": [h.to_dict() for h in holidays]})


@attendance_bp.route("/holidays", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_holiday():
    data = request.get_json(silent=True) or {}
    h = Holiday(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=data.get("name", "").strip(),
        date=datetime.strptime(data["date"], "%Y-%m-%d").date(),
        type=data.get("type", HolidayType.NATIONAL.value),
        year=int(data["date"][:4]),
        is_optional=bool(data.get("is_optional", False)),
    )
    db.session.add(h)
    db.session.commit()
    return jsonify({"holiday": h.to_dict()}), 201


@attendance_bp.route("/shifts", methods=["GET"])
@require_auth()
def list_shifts():
    shifts = Shift.query.filter_by(tenant_id=g.tenant_id, is_deleted=False, is_active=True).all()
    return jsonify({"shifts": [s.to_dict() for s in shifts]})


@attendance_bp.route("/bulk-import", methods=["POST"])
@require_auth(roles=["hr_admin"])
def bulk_import_attendance():
    """Import attendance records from a CSV file. Columns: Employee Number, Date, Status, Check In, Check Out."""
    import csv, io
    from datetime import datetime as dt, date as date_cls, timezone as tz
    from app.utils.security import sanitize_string

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400
    if not file.filename.lower().endswith(".csv"):
        return jsonify({"error": "Only CSV files are supported"}), 400

    valid_statuses = {s.value for s in AttendanceStatus}
    # Build employee lookup map: employee_number → employee
    employees = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).all()
    emp_by_number = {e.employee_number.upper(): e for e in employees}

    stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(stream)
    errors, imported, skipped = [], 0, 0

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        emp_num = (row.get("Employee Number") or row.get("employee_number") or "").strip().upper()
        date_str = (row.get("Date") or row.get("date") or "").strip()
        status_raw = (row.get("Status") or row.get("status") or "").strip().lower()
        check_in_str = (row.get("Check In") or row.get("check_in") or "").strip()
        check_out_str = (row.get("Check Out") or row.get("check_out") or "").strip()

        if not emp_num or not date_str or not status_raw:
            errors.append({"row": row_num, "reason": "Missing required columns: Employee Number, Date, Status"})
            skipped += 1
            continue

        emp = emp_by_number.get(emp_num)
        if not emp:
            errors.append({"row": row_num, "reason": f"Employee '{emp_num}' not found"})
            skipped += 1
            continue

        try:
            record_date = date_cls.fromisoformat(date_str)
        except ValueError:
            errors.append({"row": row_num, "reason": f"Invalid date format '{date_str}' — expected YYYY-MM-DD"})
            skipped += 1
            continue

        if status_raw not in valid_statuses:
            errors.append({"row": row_num, "reason": f"Invalid status '{status_raw}'"})
            skipped += 1
            continue

        try:
            status = AttendanceStatus(status_raw)
        except ValueError:
            errors.append({"row": row_num, "reason": f"Unrecognised status '{status_raw}'"})
            skipped += 1
            continue

        def _parse_time(time_str: str):
            if not time_str:
                return None
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = dt.strptime(time_str, fmt).time()
                    return dt.combine(record_date, t, tzinfo=tz.utc)
                except ValueError:
                    pass
            return None

        check_in_dt = _parse_time(check_in_str)
        check_out_dt = _parse_time(check_out_str)

        # Upsert: update existing record for the same employee+date, or create new
        existing = Attendance.query.filter_by(
            tenant_id=g.tenant_id,
            employee_id=emp.id,
            date=record_date,
            is_deleted=False,
        ).first()

        if existing:
            existing.status = status
            if check_in_dt:
                existing.check_in = check_in_dt
            if check_out_dt:
                existing.check_out = check_out_dt
            if check_in_dt and check_out_dt:
                hours = (check_out_dt - check_in_dt).total_seconds() / 3600
                existing.total_hours = round(hours, 2)
        else:
            total_hours = None
            if check_in_dt and check_out_dt:
                total_hours = round((check_out_dt - check_in_dt).total_seconds() / 3600, 2)
            att = Attendance(
                id=uuid.uuid4(),
                tenant_id=g.tenant_id,
                employee_id=emp.id,
                date=record_date,
                status=status,
                check_in=check_in_dt,
                check_out=check_out_dt,
                total_hours=total_hours,
            )
            db.session.add(att)

        imported += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error during import", "detail": str(e)}), 500

    log_action("attendance_bulk_import", f"Imported {imported} records, {skipped} skipped")
    return jsonify({"imported": imported, "skipped": skipped, "errors": errors})


@attendance_bp.route("/shifts", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_shift():
    from datetime import time as dtime
    data = request.get_json(silent=True) or {}
    shift = Shift(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=data.get("name", "").strip(),
        code=data.get("code", "").strip(),
        start_time=dtime.fromisoformat(data.get("start_time", "09:00")),
        end_time=dtime.fromisoformat(data.get("end_time", "18:00")),
        grace_in_minutes=int(data.get("grace_in_minutes", 15)),
        grace_out_minutes=int(data.get("grace_out_minutes", 15)),
        min_hours=float(data.get("min_hours", 8.0)),
        half_day_hours=float(data.get("half_day_hours", 4.0)),
        is_night_shift=bool(data.get("is_night_shift", False)),
        break_duration_minutes=int(data.get("break_duration_minutes", 60)),
        overtime_eligible=bool(data.get("overtime_eligible", True)),
        weekoff_days=data.get("weekoff_days", ["saturday", "sunday"]),
        is_flexible=bool(data.get("is_flexible", False)),
    )
    db.session.add(shift)
    db.session.commit()
    return jsonify({"shift": shift.to_dict()}), 201
