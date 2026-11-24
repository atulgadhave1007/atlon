import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import (
    SalaryComponent, EmployeeSalary, PayrollRun, Payslip, SalaryAdvance,
    TaxDeclaration, Employee, Attendance, AttendanceStatus, LeaveApplication,
    LeaveApplicationStatus, PayrollStatus, ComponentType
)
from app.utils.auth import require_auth, log_action
from app.utils.tenant_refs import reject_foreign_refs
from app.services.payroll_engine import IndiaPayrollEngine, UAEPayrollEngine, USPayrollEngine

payroll_bp = Blueprint("payroll", __name__)


def _send_payslip_emails(run, tenant_id: str) -> None:
    """Queue payslip-ready emails for all employees in a locked payroll run."""
    import calendar
    from app.services.email_service import queue_email
    from app.models import Tenant

    tenant = Tenant.query.get(tenant_id)
    month_name = calendar.month_name[run.month]
    slips = Payslip.query.filter_by(
        tenant_id=tenant_id, payroll_run_id=str(run.id), is_deleted=False
    ).all()

    for slip in slips:
        emp = Employee.query.get(slip.employee_id)
        if not emp or not emp.work_email:
            continue
        queue_email(
            emp.work_email,
            f"Your Payslip for {month_name} {run.year} is Ready",
            'email/payslip_ready.html',
            {
                'employee_name': emp.full_name,
                'employee_number': emp.employee_number,
                'month_name': month_name,
                'year': run.year,
                'net_pay': f"{float(slip.net_pay or 0):,.2f}",
                'currency': tenant.currency if tenant else 'INR',
                'company_name': tenant.name if tenant else '',
            },
        )


@payroll_bp.route("/components", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def list_components():
    components = SalaryComponent.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).order_by(SalaryComponent.sequence).all()
    return jsonify({"components": [c.to_dict() for c in components]})


@payroll_bp.route("/components", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def create_component():
    data = request.get_json(silent=True) or {}
    comp = SalaryComponent(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=data.get("name", "").strip(),
        code=data.get("code", "").strip().upper(),
        type=data.get("type", ComponentType.EARNING.value),
        calc_type=data.get("calc_type", "fixed"),
        calc_value=float(data.get("calc_value", 0)),
        formula=data.get("formula"),
        is_statutory=bool(data.get("is_statutory", False)),
        is_taxable=bool(data.get("is_taxable", True)),
        is_visible_on_payslip=bool(data.get("is_visible_on_payslip", True)),
        is_part_of_ctc=bool(data.get("is_part_of_ctc", True)),
        sequence=int(data.get("sequence", 100)),
        description=data.get("description"),
    )
    db.session.add(comp)
    db.session.commit()
    return jsonify({"component": comp.to_dict()}), 201


@payroll_bp.route("/salary", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def set_salary():
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id")
    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    emp = Employee.query.filter_by(
        id=employee_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    effective_from = datetime.strptime(data.get("effective_from", date.today().isoformat()), "%Y-%m-%d").date()

    existing = EmployeeSalary.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=employee_id,
        effective_to=None,
        is_deleted=False
    ).first()
    if existing:
        existing.effective_to = effective_from

    ctc_annual = float(data.get("ctc_annual", 0))
    ctc_monthly = ctc_annual / 12

    salary = EmployeeSalary(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=employee_id,
        effective_from=effective_from,
        ctc_annual=ctc_annual,
        ctc_monthly=ctc_monthly,
        currency=data.get("currency", "INR"),
        components=data.get("components", {}),
        india_tax_regime=data.get("india_tax_regime", "new"),
        india_professional_tax_state=data.get("india_professional_tax_state", "DEFAULT"),
        revision_reason=data.get("revision_reason"),
        revised_by_id=g.employee.id,
    )

    for f in ["india_basic", "india_hra", "uae_basic", "uae_housing", "uae_transport"]:
        if data.get(f) is not None:
            setattr(salary, f, float(data[f]))

    db.session.add(salary)
    db.session.commit()
    log_action("set_salary", "employee_salary", salary.id)
    return jsonify({"message": "Salary set", "salary": salary.to_dict()}), 201


def _salary_to_frontend(s) -> dict:
    """Reshape EmployeeSalary to include earnings/pf objects the frontend expects."""
    d = s.to_dict()
    earnings = {}
    if s.india_basic:          earnings["Basic"]               = float(s.india_basic)
    if s.india_hra:            earnings["HRA"]                 = float(s.india_hra)
    if s.india_esi_employee:   earnings["ESI (Employee)"]      = float(s.india_esi_employee)
    if s.india_pt:             earnings["Professional Tax"]    = float(s.india_pt)
    if s.india_lwf_employee:   earnings["LWF (Employee)"]      = float(s.india_lwf_employee)
    if s.uae_basic:            earnings["Basic"]               = float(s.uae_basic)
    if s.uae_housing:          earnings["Housing Allowance"]   = float(s.uae_housing)
    if s.uae_transport:        earnings["Transport Allowance"] = float(s.uae_transport)
    if s.uae_other_allowances: earnings["Other Allowances"]    = float(s.uae_other_allowances)
    for k, v in (s.components or {}).items():
        if v:
            earnings[k] = float(v)
    d["earnings"] = earnings
    d["pf"] = {
        "employee_contribution": float(s.india_pf_employee or 0),
        "employer_contribution": float(s.india_pf_employer or 0),
    }
    return d


@payroll_bp.route("/my-salary", methods=["GET"])
@require_auth()
def get_my_salary():
    """Employee self-service: view own current salary structure."""
    salary = EmployeeSalary.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        effective_to=None,
        is_deleted=False,
    ).first()
    if not salary:
        return jsonify({"salary": None})
    return jsonify({"salary": _salary_to_frontend(salary)})


@payroll_bp.route("/tax-declaration", methods=["GET"])
@require_auth()
def get_tax_declaration():
    year = int(request.args.get("year", datetime.now().year))
    decl = TaxDeclaration.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        year=year,
        is_deleted=False,
    ).first()
    return jsonify({"declaration": decl.to_dict() if decl else None})


@payroll_bp.route("/tax-declaration", methods=["POST"])
@require_auth()
def save_tax_declaration():
    data = request.get_json(silent=True) or {}
    year = int(data.get("year", datetime.now().year))
    decl = TaxDeclaration.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        year=year,
        is_deleted=False,
    ).first()
    if not decl:
        decl = TaxDeclaration(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            employee_id=g.employee.id,
            year=year,
        )
        db.session.add(decl)
    decl.regime = data.get("regime", decl.regime or "new")
    decl.section_80c = float(data.get("section_80c", decl.section_80c or 0))
    decl.section_80ccd = float(data.get("section_80ccd", decl.section_80ccd or 0))
    decl.section_80d = float(data.get("section_80d", decl.section_80d or 0))
    decl.section_80e = float(data.get("section_80e", decl.section_80e or 0))
    decl.section_80g = float(data.get("section_80g", decl.section_80g or 0))
    decl.section_80tta = float(data.get("section_80tta", decl.section_80tta or 0))
    decl.hra_rent_paid = float(data.get("hra_rent_paid", decl.hra_rent_paid or 0))
    decl.hra_city_type = data.get("hra_city_type", decl.hra_city_type or "metro")
    decl.home_loan_interest = float(data.get("home_loan_interest", decl.home_loan_interest or 0))
    decl.home_loan_principal = float(data.get("home_loan_principal", decl.home_loan_principal or 0))
    decl.other_deductions = data.get("other_deductions", decl.other_deductions or {})
    decl.declarations = data.get("declarations", decl.declarations or {})
    db.session.commit()
    log_action("save_tax_declaration", "tax_declaration", decl.id)
    return jsonify({"message": "Tax declaration saved", "declaration": decl.to_dict()})


@payroll_bp.route("/salary/<employee_id>", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin", "employee"])
def get_salary(employee_id):
    if g.role == "employee" and str(g.employee.id) != employee_id:
        return jsonify({"error": "Access denied"}), 403
    salary = EmployeeSalary.query.filter_by(
        tenant_id=g.tenant_id, employee_id=employee_id,
        effective_to=None, is_deleted=False
    ).first()
    if not salary:
        return jsonify({"error": "No salary set for this employee"}), 404
    return jsonify({"salary": salary.to_dict()})


@payroll_bp.route("/run", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def run_payroll():
    from app.schemas.payroll import PayrollRunSchema
    from app.schemas import validate_request
    data = request.get_json(silent=True) or {}
    validated, err = validate_request(PayrollRunSchema(), data)
    if err:
        return err
    year = validated["year"]
    month = validated["month"]
    employee_ids = validated.get("employee_ids")

    existing = PayrollRun.query.filter_by(
        tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
    ).first()
    if existing and existing.status == PayrollStatus.LOCKED:
        return jsonify({"error": "Payroll for this period is locked"}), 409

    if not existing:
        run = PayrollRun(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            year=year,
            month=month,
            name=f"Payroll {year}-{month:02d}",
            status=PayrollStatus.PROCESSING,
            processed_by_id=g.employee.id,
            processed_at=datetime.now(timezone.utc),
        )
        db.session.add(run)
        db.session.flush()
    else:
        run = existing
        run.status = PayrollStatus.PROCESSING

    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    )
    if employee_ids:
        employees = employees.filter(Employee.id.in_(employee_ids))
    employees = employees.all()

    from app.models import Tenant
    tenant = Tenant.query.get(g.tenant_id)
    country = tenant.country.value if tenant.country else "IN"

    total_gross = Decimal("0")
    total_deductions = Decimal("0")
    total_net = Decimal("0")
    payslip_count = 0

    for emp in employees:
        salary = EmployeeSalary.query.filter_by(
            tenant_id=g.tenant_id, employee_id=emp.id,
            effective_to=None, is_deleted=False
        ).first()
        if not salary:
            continue

        existing_slip = Payslip.query.filter_by(
            tenant_id=g.tenant_id, employee_id=emp.id,
            year=year, month=month, is_deleted=False
        ).first()
        if existing_slip:
            db.session.delete(existing_slip)
            db.session.flush()

        att_records = Attendance.query.filter_by(
            tenant_id=g.tenant_id, employee_id=emp.id, is_deleted=False
        ).filter(
            db.extract("year", Attendance.date) == year,
            db.extract("month", Attendance.date) == month
        ).all()

        import calendar
        working_days = 0
        _, total_days = calendar.monthrange(year, month)
        for att in att_records:
            if att.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE,
                               AttendanceStatus.REGULARIZED, AttendanceStatus.WORK_FROM_HOME):
                working_days += 1
            elif att.status == AttendanceStatus.HALF_DAY:
                working_days += 0.5

        leave_days = sum(
            float(a.days_count) for a in LeaveApplication.query.filter_by(
                tenant_id=g.tenant_id, employee_id=emp.id,
                status=LeaveApplicationStatus.APPROVED, is_deleted=False
            ).filter(
                db.extract("year", LeaveApplication.from_date) == year,
                db.extract("month", LeaveApplication.from_date) == month
            ).all() if a.leave_type and a.leave_type.is_paid
        )
        paid_days = min(working_days + leave_days, total_days)
        lop_days = max(0, total_days - working_days - leave_days)

        if country == "IN":
            engine = IndiaPayrollEngine(emp, salary, paid_days, total_days, year, month)
        elif country == "AE":
            engine = UAEPayrollEngine(emp, salary, paid_days, total_days, year, month)
        elif country == "US":
            engine = USPayrollEngine(emp, salary, paid_days, total_days, year, month)
        else:
            engine = IndiaPayrollEngine(emp, salary, paid_days, total_days, year, month)

        result = engine.calculate()

        advance = SalaryAdvance.query.filter_by(
            tenant_id=g.tenant_id, employee_id=emp.id, status="approved", is_deleted=False
        ).filter(
            SalaryAdvance.repayment_start_year == year,
            SalaryAdvance.repayment_start_month == month
        ).first()
        advance_deduction = float(advance.monthly_deduction or 0) if advance else 0

        payslip = Payslip(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            payroll_run_id=run.id,
            employee_id=emp.id,
            year=year,
            month=month,
            working_days=total_days,
            paid_days=paid_days,
            lop_days=lop_days,
            earnings=result["earnings"],
            deductions=result["deductions"],
            employer_contributions=result.get("employer_contributions", {}),
            gross_earnings=Decimal(str(result["gross"])),
            total_deductions=Decimal(str(result["total_deductions"])) + Decimal(str(advance_deduction)),
            net_pay=Decimal(str(result["net"])) - Decimal(str(advance_deduction)),
            advance_deduction=Decimal(str(advance_deduction)),
            **{k: Decimal(str(v)) for k, v in result.get("statutory", {}).items()},
        )
        db.session.add(payslip)

        total_gross += Decimal(str(result["gross"]))
        total_deductions += Decimal(str(result["total_deductions"]))
        total_net += Decimal(str(result["net"]))
        payslip_count += 1

    run.status = PayrollStatus.PROCESSED
    run.employee_count = payslip_count
    run.total_gross = total_gross
    run.total_deductions = total_deductions
    run.total_net = total_net
    db.session.commit()
    log_action("run_payroll", "payroll_run", run.id)

    return jsonify({
        "message": "Payroll processed",
        "run_id": str(run.id),
        "employee_count": payslip_count,
        "total_gross": float(total_gross),
        "total_net": float(total_net),
    })


@payroll_bp.route("/runs", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def list_runs():
    runs = PayrollRun.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(PayrollRun.year.desc(), PayrollRun.month.desc()).limit(24).all()
    return jsonify({"runs": [r.to_dict() for r in runs]})


@payroll_bp.route("/runs/<run_id>/lock", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def lock_run(run_id):
    run = PayrollRun.query.filter_by(
        id=run_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if run.status not in (PayrollStatus.PROCESSED, PayrollStatus.APPROVED):
        return jsonify({"error": "Only processed payroll can be locked"}), 409
    run.status = PayrollStatus.LOCKED
    run.locked_at = datetime.now(timezone.utc)
    run.locked_by_id = g.employee.id
    db.session.commit()
    log_action("lock_payroll", "payroll_run", run.id)

    _send_payslip_emails(run, g.tenant_id)
    return jsonify({"message": "Payroll locked"})


@payroll_bp.route("/payslips", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin", "employee"])
def list_payslips():
    employee_id = request.args.get("employee_id")
    year = request.args.get("year")
    if g.role == "employee":
        employee_id = str(g.employee.id)

    q = Payslip.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if employee_id:
        q = q.filter_by(employee_id=employee_id)
    if year:
        q = q.filter_by(year=int(year))

    payslips = q.order_by(Payslip.year.desc(), Payslip.month.desc()).all()
    return jsonify({"payslips": [p.to_dict() for p in payslips]})


@payroll_bp.route("/payslips/<slip_id>", methods=["GET"])
@require_auth()
def get_payslip(slip_id):
    slip = Payslip.query.filter_by(
        id=slip_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if g.role == "employee" and str(g.employee.id) != str(slip.employee_id):
        return jsonify({"error": "Access denied"}), 403
    return jsonify(slip.to_dict())


@payroll_bp.route("/payslips/<slip_id>/download", methods=["GET"])
@require_auth()
def download_payslip(slip_id):
    """Generate and return payslip as PDF."""
    import io
    from flask import send_file
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    slip = Payslip.query.filter_by(
        id=slip_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if g.role == "employee" and str(g.employee.id) != str(slip.employee_id):
        return jsonify({"error": "Access denied"}), 403

    emp = Employee.query.get(slip.employee_id)
    from app.models import Tenant
    tenant = Tenant.query.get(g.tenant_id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{tenant.name if tenant else 'Company'}</b>", styles["Title"]))
    story.append(Paragraph(f"Payslip for {slip.month}/{slip.year}", styles["Heading2"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Employee: {emp.full_name if emp else '-'}", styles["Normal"]))
    story.append(Paragraph(f"Employee No: {emp.employee_number if emp else '-'}", styles["Normal"]))
    story.append(Spacer(1, 12))

    earnings = slip.earnings or {}
    deductions = slip.deductions or {}
    data_rows = [["Earnings", "Amount", "Deductions", "Amount"]]
    earn_keys = list(earnings.keys())
    ded_keys = list(deductions.keys())
    for i in range(max(len(earn_keys), len(ded_keys))):
        ek = earn_keys[i] if i < len(earn_keys) else ""
        dk = ded_keys[i] if i < len(ded_keys) else ""
        data_rows.append([
            ek.replace("_", " ").title() if ek else "",
            f"{float(earnings[ek]):,.2f}" if ek else "",
            dk.replace("_", " ").title() if dk else "",
            f"{float(deductions[dk]):,.2f}" if dk else "",
        ])
    data_rows.append(["Gross Salary", f"{float(slip.gross_salary or 0):,.2f}",
                      "Total Deductions", f"{float(slip.total_deductions or 0):,.2f}"])
    data_rows.append(["Net Pay", f"{float(slip.net_salary or 0):,.2f}", "", ""])

    t = Table(data_rows, colWidths=[55*mm, 35*mm, 55*mm, 35*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#22c55e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9fafb")]),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)
    doc.build(story)

    return send_file(
        io.BytesIO(buf.getvalue()),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"payslip_{slip.month}_{slip.year}.pdf",
    )


@payroll_bp.route("/salary-structures", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def list_salary_structures():
    """List all active employee salary structures."""
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 100)
    q = EmployeeSalary.query.filter_by(
        tenant_id=g.tenant_id, effective_to=None, is_deleted=False
    )
    employee_id = request.args.get("employee_id")
    if employee_id:
        q = q.filter_by(employee_id=employee_id)

    pagination = q.order_by(EmployeeSalary.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    result = []
    for s in pagination.items:
        emp = Employee.query.get(s.employee_id)
        d = s.to_dict()
        d["employee_name"] = emp.full_name if emp else "-"
        d["employee_number"] = emp.employee_number if emp else "-"
        result.append(d)
    return jsonify({"structures": result, "total": pagination.total, "page": page})


@payroll_bp.route("/salary-structures", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def create_salary_structure():
    """Create/update employee salary structure (delegates to set_salary logic)."""
    return set_salary()


@payroll_bp.route("/reports/summary", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def payroll_summary_report():
    """Payroll summary for a given month/year."""
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    runs = PayrollRun.query.filter_by(
        tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
    ).all()
    if not runs:
        return jsonify({"year": year, "month": month, "runs": [], "totals": {}})
    run_ids = [str(r.id) for r in runs]
    slips = Payslip.query.filter(
        Payslip.tenant_id == g.tenant_id,
        Payslip.payroll_run_id.in_(run_ids),
        Payslip.is_deleted == False,
    ).all()
    total_gross = sum(float(s.gross_salary or 0) for s in slips)
    total_net = sum(float(s.net_salary or 0) for s in slips)
    total_deductions = sum(float(s.total_deductions or 0) for s in slips)
    return jsonify({
        "year": year, "month": month,
        "runs": [r.to_dict() for r in runs],
        "payslip_count": len(slips),
        "totals": {
            "gross": total_gross,
            "net": total_net,
            "deductions": total_deductions,
        },
    })


@payroll_bp.route("/export", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def export_payroll():
    """Export payroll register as CSV."""
    import csv, io
    from flask import Response
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    slips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=year, month=month, is_deleted=False
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Employee Number", "Employee Name", "Gross Salary", "Deductions", "Net Salary", "Month", "Year"])
    for s in slips:
        emp = Employee.query.get(s.employee_id)
        writer.writerow([
            emp.employee_number if emp else "-",
            emp.full_name if emp else "-",
            float(s.gross_salary or 0),
            float(s.total_deductions or 0),
            float(s.net_salary or 0),
            month, year,
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=payroll_{month}_{year}.csv"},
    )


@payroll_bp.route("/form16/<int:year>", methods=["GET"])
@require_auth()
def download_form16(year):
    import io
    from flask import send_file
    from app.services.form16_generator import generate_form16_pdf
    from app.models import Tenant

    if g.role == "employee":
        emp = g.employee
    else:
        emp_id = request.args.get("employee_id")
        if not emp_id:
            return jsonify({"error": "employee_id required"}), 400
        emp = Employee.query.filter_by(id=emp_id, tenant_id=g.tenant_id, is_deleted=False).first_or_404()

    payslips = Payslip.query.filter(
        Payslip.tenant_id == g.tenant_id,
        Payslip.employee_id == emp.id,
        Payslip.is_deleted == False,
        db.or_(
            db.and_(Payslip.year == year, Payslip.month >= 4),
            db.and_(Payslip.year == year + 1, Payslip.month <= 3),
        ),
    ).all()

    tax_decl = TaxDeclaration.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp.id, year=year, is_deleted=False
    ).first()
    tenant = Tenant.query.get(g.tenant_id)
    pdf_bytes = generate_form16_pdf(emp, payslips, tax_decl, tenant, year)
    filename = f"Form16_{emp.employee_number}_{year}-{str(year + 1)[-2:]}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@payroll_bp.route("/form16/<int:year>/bulk", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def bulk_form16(year):
    import io, zipfile
    from flask import send_file
    from app.services.form16_generator import generate_form16_pdf
    from app.models import Tenant

    tenant = Tenant.query.get(g.tenant_id)
    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).all()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for emp in employees:
            payslips = Payslip.query.filter(
                Payslip.tenant_id == g.tenant_id,
                Payslip.employee_id == emp.id,
                Payslip.is_deleted == False,
                db.or_(
                    db.and_(Payslip.year == year, Payslip.month >= 4),
                    db.and_(Payslip.year == year + 1, Payslip.month <= 3),
                ),
            ).all()
            if not payslips:
                continue
            tax_decl = TaxDeclaration.query.filter_by(
                tenant_id=g.tenant_id, employee_id=emp.id, year=year, is_deleted=False
            ).first()
            pdf_bytes = generate_form16_pdf(emp, payslips, tax_decl, tenant, year)
            zf.writestr(f"Form16_{emp.employee_number}_{year}.pdf", pdf_bytes)

    zip_buf.seek(0)
    return send_file(zip_buf, mimetype="application/zip",
                     as_attachment=True, download_name=f"Form16_Bulk_{year}.zip")


@payroll_bp.route("/pf-ecr", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def pf_ecr():
    import io
    from flask import Response
    from app.services.statutory_exports import generate_pf_ecr

    month_str = request.args.get("month", "")
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        return jsonify({"error": "month required as YYYY-MM"}), 400

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=y, month=m, is_deleted=False
    ).all()
    emp_ids = [str(p.employee_id) for p in payslips]
    emps = {str(e.id): e for e in Employee.query.filter(
        Employee.id.in_(emp_ids), Employee.tenant_id == g.tenant_id,
    ).all()}
    csv_data = generate_pf_ecr(payslips, emps)
    return Response(
        csv_data, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=PF_ECR_{month_str}.csv"},
    )


@payroll_bp.route("/esi-return", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def esi_return():
    from flask import Response
    from app.services.statutory_exports import generate_esi_return

    month_str = request.args.get("month", "")
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        return jsonify({"error": "month required as YYYY-MM"}), 400

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=y, month=m, is_deleted=False
    ).all()
    emp_ids = [str(p.employee_id) for p in payslips]
    emps = {str(e.id): e for e in Employee.query.filter(
        Employee.id.in_(emp_ids), Employee.tenant_id == g.tenant_id,
    ).all()}
    csv_data = generate_esi_return(payslips, emps)
    return Response(
        csv_data, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ESI_Return_{month_str}.csv"},
    )


@payroll_bp.route("/wps-sif", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def wps_sif():
    from flask import Response
    from app.models import EmployeeBankDetail, Tenant
    from app.services.statutory_exports import generate_wps_sif

    month_str = request.args.get("month", "")
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        return jsonify({"error": "month required as YYYY-MM"}), 400

    pay_date_str = request.args.get("payment_date", "")
    try:
        pay_date = datetime.strptime(pay_date_str, "%Y-%m-%d").date() if pay_date_str else date(y, m, 28)
    except ValueError:
        return jsonify({"error": "payment_date must be YYYY-MM-DD"}), 400

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=y, month=m, is_deleted=False
    ).all()
    emp_ids = [str(p.employee_id) for p in payslips]
    emps = {str(e.id): e for e in Employee.query.filter(
        Employee.id.in_(emp_ids), Employee.tenant_id == g.tenant_id,
    ).all()}
    banks = {str(b.employee_id): b for b in EmployeeBankDetail.query.filter(
        EmployeeBankDetail.employee_id.in_(emp_ids),
        EmployeeBankDetail.tenant_id == g.tenant_id,
        EmployeeBankDetail.is_primary == True,
        EmployeeBankDetail.is_deleted == False,
    ).all()}
    tenant = Tenant.query.get(g.tenant_id)
    sif_data = generate_wps_sif(payslips, emps, banks, tenant, pay_date)
    return Response(
        sif_data, mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=WPS_SIF_{month_str}.sif"},
    )


@payroll_bp.route("/neft-file", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def neft_file():
    from flask import Response
    from app.models import EmployeeBankDetail, Tenant
    from app.services.statutory_exports import generate_neft_file

    month_str = request.args.get("month", "")
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        return jsonify({"error": "month required as YYYY-MM"}), 400

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=y, month=m, is_deleted=False
    ).all()
    emp_ids = [str(p.employee_id) for p in payslips]
    emps = {str(e.id): e for e in Employee.query.filter(
        Employee.id.in_(emp_ids), Employee.tenant_id == g.tenant_id,
    ).all()}
    banks = {str(b.employee_id): b for b in EmployeeBankDetail.query.filter(
        EmployeeBankDetail.employee_id.in_(emp_ids),
        EmployeeBankDetail.tenant_id == g.tenant_id,
        EmployeeBankDetail.is_primary == True,
        EmployeeBankDetail.is_deleted == False,
    ).all()}
    tenant = Tenant.query.get(g.tenant_id)
    csv_data = generate_neft_file(payslips, emps, banks, tenant)
    return Response(
        csv_data, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=NEFT_{month_str}.csv"},
    )


@payroll_bp.route("/tally-xml", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def tally_xml():
    from flask import Response
    from app.models import Tenant
    from app.services.statutory_exports import generate_tally_xml

    month_str = request.args.get("month", "")
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except (ValueError, IndexError):
        return jsonify({"error": "month required as YYYY-MM"}), 400

    payslips = Payslip.query.filter_by(
        tenant_id=g.tenant_id, year=y, month=m, is_deleted=False
    ).all()
    emp_ids = [str(p.employee_id) for p in payslips]
    emps = {str(e.id): e for e in Employee.query.filter(
        Employee.id.in_(emp_ids), Employee.tenant_id == g.tenant_id,
    ).all()}
    tenant = Tenant.query.get(g.tenant_id)
    xml_data = generate_tally_xml(payslips, emps, y, m, tenant)
    return Response(
        xml_data, mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename=Tally_Payroll_{month_str}.xml"},
    )


@payroll_bp.route("/advances", methods=["POST"])
@require_auth(roles=["employee", "hr_admin"])
def request_advance():
    data = request.get_json(silent=True) or {}
    emp_id = data.get("employee_id") or str(g.employee.id)
    if g.role == "employee":
        emp_id = str(g.employee.id)

    _ref_err = reject_foreign_refs({"employee_id": emp_id}, {"employee_id": "Employee"})
    if _ref_err:
        return _ref_err
    advance = SalaryAdvance(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp_id,
        requested_amount=float(data.get("amount", 0)),
        reason=data.get("reason", "").strip(),
        repayment_months=int(data.get("repayment_months", 1)),
        status="pending",
    )
    db.session.add(advance)
    db.session.commit()
    return jsonify({"message": "Advance request submitted", "id": str(advance.id)}), 201


@payroll_bp.route("/advances/<advance_id>/approve", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def approve_advance(advance_id):
    data = request.get_json(silent=True) or {}
    advance = SalaryAdvance.query.filter_by(
        id=advance_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    action = data.get("action", "approve")
    if action == "approve":
        advance.status = "approved"
        advance.approved_amount = float(data.get("approved_amount", advance.requested_amount))
        advance.approved_by_id = g.employee.id
        advance.approved_at = datetime.now(timezone.utc)
        advance.repayment_start_month = data.get("repayment_start_month", datetime.now().month)
        advance.repayment_start_year = data.get("repayment_start_year", datetime.now().year)
        advance.monthly_deduction = advance.approved_amount / advance.repayment_months
        advance.outstanding = advance.approved_amount
    else:
        advance.status = "rejected"
    db.session.commit()
    return jsonify({"message": f"Advance {action}d"})
