import io, csv
from datetime import datetime, date
from flask import Blueprint, request, jsonify, g, make_response, Response
from app.extensions import db
from app.models import Employee, Attendance, AttendanceStatus, Payslip, PayrollRun, LeaveApplication
from app.utils.auth import require_auth

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/headcount", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin", "manager"])
def headcount():
    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).all()

    by_dept = {}
    by_type = {}
    by_status = {}

    for e in employees:
        dept = e.department.name if e.department else "Unassigned"
        by_dept[dept] = by_dept.get(dept, 0) + 1
        emp_type = e.employment_type.value if e.employment_type else "unknown"
        by_type[emp_type] = by_type.get(emp_type, 0) + 1
        status = e.status.value if e.status else "unknown"
        by_status[status] = by_status.get(status, 0) + 1

    active = sum(1 for e in employees if e.is_active and not e.is_deleted)
    total = len(employees)

    return jsonify({
        "total": total,
        "active": active,
        "by_department": by_dept,
        "by_employment_type": by_type,
        "by_status": by_status,
    })


@reports_bp.route("/headcount/export", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def headcount_export():
    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Employee Number", "Name", "Email", "Department", "Designation",
        "Employment Type", "Status", "Date of Joining", "Manager"
    ])
    for e in employees:
        writer.writerow([
            e.employee_number, e.full_name, e.work_email,
            e.department.name if e.department else "",
            e.designation.name if e.designation else "",
            e.employment_type.value if e.employment_type else "",
            e.status.value if e.status else "",
            e.date_of_joining.isoformat() if e.date_of_joining else "",
            e.reporting_manager.full_name if e.reporting_manager else "",
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = "attachment; filename=headcount.csv"
    return response


@reports_bp.route("/attendance-summary", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def attendance_summary():
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))

    records = Attendance.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).filter(
        db.extract("year", Attendance.date) == year,
        db.extract("month", Attendance.date) == month,
    ).all()

    summary = {}
    for rec in records:
        eid = str(rec.employee_id)
        if eid not in summary:
            summary[eid] = {
                "employee_id": eid,
                "present": 0, "absent": 0, "late": 0,
                "half_day": 0, "on_leave": 0, "wfh": 0,
                "total_hours": 0.0, "overtime_hours": 0.0,
            }
        s = summary[eid]
        st = rec.status.value if rec.status else ""
        if st in s:
            s[st] += 1
        s["total_hours"] += float(rec.working_hours or 0)
        s["overtime_hours"] += float(rec.overtime_hours or 0)

    return jsonify({"year": year, "month": month, "summary": list(summary.values())})


@reports_bp.route("/payroll-register", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def payroll_register():
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
    ).all()

    total_gross = sum(float(p.gross_earnings or 0) for p in payslips)
    total_deductions = sum(float(p.total_deductions or 0) for p in payslips)
    total_net = sum(float(p.net_pay or 0) for p in payslips)

    return jsonify({
        "year": year,
        "month": month,
        "employee_count": len(payslips),
        "total_gross": total_gross,
        "total_deductions": total_deductions,
        "total_net": total_net,
        "payslips": [p.to_dict() for p in payslips],
    })


@reports_bp.route("/payroll-register/export", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def payroll_register_export():
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Employee Number", "Name", "Month", "Year",
        "Paid Days", "LOP Days", "Gross", "Deductions", "Net Pay",
        "PF Employee", "PF Employer", "ESI Employee", "ESI Employer", "PT", "TDS"
    ])

    for p in payslips:
        emp = Employee.query.get(p.employee_id)
        writer.writerow([
            emp.employee_number if emp else "",
            emp.full_name if emp else "",
            month, year,
            float(p.paid_days or 0), float(p.lop_days or 0),
            float(p.gross_earnings or 0), float(p.total_deductions or 0), float(p.net_pay or 0),
            float(p.india_pf_employee or 0), float(p.india_pf_employer or 0),
            float(p.india_esi_employee or 0), float(p.india_esi_employer or 0),
            float(p.india_pt or 0), float(p.india_tds or 0),
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f"attachment; filename=payroll_{year}_{month:02d}.csv"
    return response


@reports_bp.route("/<report_type>", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin", "manager"])
def generic_report(report_type):
    """Generic report router — maps frontend report type names to CSV exports."""
    from flask import Response
    fmt = request.args.get("format", "json")
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))

    output = io.StringIO()
    writer = csv.writer(output)
    filename = f"{report_type}_{year}.csv"

    if report_type in ("attendance", "attendance-summary"):
        writer.writerow(["Employee Number", "Employee Name", "Month", "Year", "Present Days", "Absent Days", "WFH Days", "Late Days"])
        employees = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False, is_active=True).all()
        for emp in employees:
            records = Attendance.query.filter_by(
                tenant_id=g.tenant_id, employee_id=emp.id, is_deleted=False
            ).filter(
                db.extract("year", Attendance.date) == year,
                db.extract("month", Attendance.date) == month,
            ).all()
            present = sum(1 for r in records if r.status and r.status.value in ("present", "regularized", "on_duty", "comp_off"))
            absent = sum(1 for r in records if r.status and r.status.value == "absent")
            wfh = sum(1 for r in records if r.status and r.status.value == "work_from_home")
            late = sum(1 for r in records if r.status and r.status.value in ("late", "half_day"))
            writer.writerow([emp.employee_number, emp.full_name, month, year, present, absent, wfh, late])
        filename = f"attendance_{year}_{month:02d}.csv"

    elif report_type in ("leave", "leave-summary"):
        from app.models import LeaveBalance, LeaveType
        writer.writerow(["Employee Number", "Employee Name", "Leave Type", "Credited", "Availed", "Balance"])
        employees = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False, is_active=True).all()
        for emp in employees:
            balances = LeaveBalance.query.filter_by(
                tenant_id=g.tenant_id, employee_id=emp.id, year=year, is_deleted=False
            ).all()
            for b in balances:
                lt = LeaveType.query.get(b.leave_type_id)
                writer.writerow([emp.employee_number, emp.full_name, lt.name if lt else "-",
                                  float(b.credited or 0), float(b.availed or 0), b.balance])
        filename = f"leave_{year}.csv"

    elif report_type in ("payroll", "payroll-register"):
        writer.writerow(["Employee Number", "Employee Name", "Month", "Year", "Gross", "Deductions", "Net"])
        payslips = Payslip.query.filter_by(
            tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
        ).all()
        for p in payslips:
            emp = Employee.query.get(p.employee_id)
            writer.writerow([emp.employee_number if emp else "-", emp.full_name if emp else "-",
                              month, year, float(p.gross_salary or 0),
                              float(p.total_deductions or 0), float(p.net_salary or 0)])
        filename = f"payroll_{year}_{month:02d}.csv"

    elif report_type in ("employees", "headcount"):
        writer.writerow(["Employee Number", "Name", "Department", "Designation", "Employment Type", "Status", "Joining Date"])
        employees = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).all()
        for emp in employees:
            writer.writerow([
                emp.employee_number, emp.full_name,
                emp.department.name if emp.department else "-",
                emp.designation.name if emp.designation else "-",
                emp.employment_type.value if emp.employment_type else "-",
                emp.status.value if emp.status else "-",
                emp.date_of_joining.isoformat() if emp.date_of_joining else "-",
            ])
        filename = "employees.csv"

    elif report_type in ("performance", "kra"):
        from app.models import Goal, AppraisalCycle
        writer.writerow(["Employee Number", "Employee Name", "Goal Title", "Weightage", "Self Rating", "Manager Rating", "Cycle"])
        goals = Goal.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).all()
        for goal in goals:
            emp = Employee.query.get(goal.employee_id)
            cycle = AppraisalCycle.query.get(goal.cycle_id) if goal.cycle_id else None
            cycle_name = cycle.name if cycle else "-"
            writer.writerow([
                emp.employee_number if emp else "-", emp.full_name if emp else "-",
                goal.title, float(goal.weightage or 0),
                float(goal.self_rating or 0), float(goal.manager_rating or 0), cycle_name,
            ])
        filename = "performance.csv"

    elif report_type in ("statutory", "pf_ecr", "esi", "pt", "tds"):
        writer.writerow(["Employee Number", "Employee Name", "Month", "Year", "PF Employee", "PF Employer", "ESI Employee", "ESI Employer", "PT", "TDS"])
        payslips = Payslip.query.filter_by(
            tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
        ).all()
        for p in payslips:
            emp = Employee.query.get(p.employee_id)
            writer.writerow([
                emp.employee_number if emp else "-", emp.full_name if emp else "-",
                month, year,
                float(p.earnings.get("pf_employee", 0) if p.earnings else 0),
                float(p.earnings.get("pf_employer", 0) if p.earnings else 0),
                float(p.deductions.get("esi_employee", 0) if p.deductions else 0),
                float(p.deductions.get("esi_employer", 0) if p.deductions else 0),
                float(p.deductions.get("professional_tax", 0) if p.deductions else 0),
                float(p.deductions.get("tds", 0) if p.deductions else 0),
            ])
        filename = f"{report_type}_{year}_{month:02d}.csv"

    else:
        writer.writerow(["Report Type", "Status"])
        writer.writerow([report_type, "Report not yet configured"])

    if fmt == "csv" or request.headers.get("Accept", "").startswith("text/csv"):
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    return jsonify({"message": f"Report '{report_type}' generated", "rows": output.getvalue().count("\n") - 1})


@reports_bp.route("/dashboard/ams", methods=["GET"])
@require_auth()
def ams_dashboard():
    """AMS (Attendance Management System) summary dashboard."""
    from datetime import timedelta, timezone
    emp = g.employee
    today = date.today()

    # Last 6 days attendance
    recent = Attendance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id, is_deleted=False
    ).filter(Attendance.date >= today - timedelta(days=6)).order_by(Attendance.date.desc()).all()

    # Leave balance
    from app.models import LeaveBalance
    balances = LeaveBalance.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id,
        year=today.year, is_deleted=False
    ).all()

    # Upcoming holidays
    from app.models import Holiday
    holidays = Holiday.query.filter(
        Holiday.tenant_id == g.tenant_id,
        Holiday.date >= today,
        Holiday.date <= today + timedelta(days=30),
        Holiday.is_deleted == False
    ).order_by(Holiday.date).limit(5).all()

    # Pending leave applications + recent leave history
    from app.models import LeaveApplication, LeaveApplicationStatus
    pending_count = LeaveApplication.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id,
        status=LeaveApplicationStatus.PENDING, is_deleted=False
    ).count()

    recent_leaves = LeaveApplication.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id, is_deleted=False
    ).order_by(LeaveApplication.from_date.desc()).limit(5).all()

    return jsonify({
        "recent_attendance": [
            {
                "date": r.date.isoformat(),
                "status": r.status.value,
                "check_in": r.check_in.isoformat() if r.check_in else None,
                "check_out": r.check_out.isoformat() if r.check_out else None,
                "hours": float(r.working_hours or 0),
            }
            for r in recent
        ],
        "recent_leaves": [
            {
                "from_date": la.from_date.isoformat() if la.from_date else None,
                "to_date": la.to_date.isoformat() if la.to_date else None,
                "days_count": float(la.days_count or 1),
                "leave_type": la.leave_type.name if la.leave_type else "",
                "status": la.status.value if la.status else "pending",
            }
            for la in recent_leaves
        ],
        "leave_balance": [
            {"type": b.leave_type.name if b.leave_type else "", "balance": b.balance}
            for b in balances
        ],
        "upcoming_holidays": [
            {"date": h.date.isoformat(), "name": h.name, "type": h.type.value}
            for h in holidays
        ],
        "pending_leave_applications": pending_count,
    })
