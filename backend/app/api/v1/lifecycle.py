import uuid
from datetime import datetime, timezone, date
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import Employee, EmployeeLifecycleEvent, EmployeeStatus
from app.utils.auth import require_auth, log_action

lifecycle_bp = Blueprint("lifecycle", __name__)


@lifecycle_bp.route("/confirm/<emp_id>", methods=["POST"])
@require_auth(roles=["hr_admin"])
def confirm_employee(emp_id):
    data = request.get_json(silent=True) or {}
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    effective_date = datetime.strptime(
        data.get("effective_date", date.today().isoformat()), "%Y-%m-%d"
    ).date()

    old_status = emp.status
    emp.status = EmployeeStatus.ACTIVE
    emp.date_of_confirmation = effective_date

    event = EmployeeLifecycleEvent(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp.id,
        event_type="confirmation",
        effective_date=effective_date,
        from_value={"status": old_status.value},
        to_value={"status": EmployeeStatus.ACTIVE.value},
        remarks=data.get("remarks", ""),
        initiated_by_id=g.employee.id,
    )
    db.session.add(event)
    db.session.commit()
    log_action("confirm_employee", "employee", emp.id)
    return jsonify({"message": "Employee confirmed", "employee": emp.to_dict()})


@lifecycle_bp.route("/pending-confirmations", methods=["GET"])
@require_auth(roles=["hr_admin"])
def pending_confirmations():
    today = date.today()
    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, status=EmployeeStatus.PROBATION, is_deleted=False
    ).filter(
        Employee.probation_end_date <= today
    ).all()
    return jsonify({
        "pending": [{
            "id": str(e.id),
            "name": e.full_name,
            "employee_number": e.employee_number,
            "date_of_joining": e.date_of_joining.isoformat() if e.date_of_joining else None,
            "probation_end_date": e.probation_end_date.isoformat() if e.probation_end_date else None,
        } for e in employees]
    })


@lifecycle_bp.route("/transfer/<emp_id>", methods=["POST"])
@require_auth(roles=["hr_admin"])
def transfer_employee(emp_id):
    data = request.get_json(silent=True) or {}
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    effective_date = datetime.strptime(
        data.get("effective_date", date.today().isoformat()), "%Y-%m-%d"
    ).date()

    old_values = {
        "department_id": str(emp.department_id) if emp.department_id else None,
        "branch_id": str(emp.branch_id) if emp.branch_id else None,
        "reporting_manager_id": str(emp.reporting_manager_id) if emp.reporting_manager_id else None,
    }
    new_values = {}

    if data.get("department_id"):
        emp.department_id = data["department_id"]
        new_values["department_id"] = data["department_id"]
    if data.get("branch_id"):
        emp.branch_id = data["branch_id"]
        new_values["branch_id"] = data["branch_id"]
    if data.get("reporting_manager_id"):
        emp.reporting_manager_id = data["reporting_manager_id"]
        new_values["reporting_manager_id"] = data["reporting_manager_id"]

    event = EmployeeLifecycleEvent(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp.id,
        event_type="transfer",
        effective_date=effective_date,
        from_value=old_values,
        to_value=new_values,
        remarks=data.get("remarks", ""),
        initiated_by_id=g.employee.id,
    )
    db.session.add(event)
    db.session.commit()
    log_action("transfer_employee", "employee", emp.id, old_values=old_values, new_values=new_values)
    return jsonify({"message": "Transfer recorded", "employee": emp.to_dict()})


@lifecycle_bp.route("/promote/<emp_id>", methods=["POST"])
@require_auth(roles=["hr_admin"])
def promote_employee(emp_id):
    data = request.get_json(silent=True) or {}
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    effective_date = datetime.strptime(
        data.get("effective_date", date.today().isoformat()), "%Y-%m-%d"
    ).date()

    old_desig_id = str(emp.designation_id) if emp.designation_id else None
    new_desig_id = data.get("designation_id")

    if new_desig_id:
        emp.designation_id = new_desig_id

    if data.get("new_ctc"):
        from app.models import EmployeeSalary
        curr_salary = EmployeeSalary.query.filter_by(
            tenant_id=g.tenant_id, employee_id=emp.id, effective_to=None, is_deleted=False
        ).first()
        if curr_salary:
            curr_salary.effective_to = effective_date
        new_salary = EmployeeSalary(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            employee_id=emp.id,
            effective_from=effective_date,
            ctc_annual=float(data["new_ctc"]),
            ctc_monthly=float(data["new_ctc"]) / 12,
            revision_reason=f"Promotion: {data.get('remarks', '')}",
            revised_by_id=g.employee.id,
        )
        db.session.add(new_salary)

    event = EmployeeLifecycleEvent(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp.id,
        event_type="promotion",
        effective_date=effective_date,
        from_value={"designation_id": old_desig_id},
        to_value={"designation_id": new_desig_id, "new_ctc": data.get("new_ctc")},
        remarks=data.get("remarks", ""),
        initiated_by_id=g.employee.id,
    )
    db.session.add(event)
    db.session.commit()
    log_action("promote_employee", "employee", emp.id)
    return jsonify({"message": "Promotion recorded", "employee": emp.to_dict()})


@lifecycle_bp.route("/events/<emp_id>", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def lifecycle_events(emp_id):
    events = EmployeeLifecycleEvent.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp_id
    ).order_by(EmployeeLifecycleEvent.effective_date.desc()).all()
    return jsonify({"events": [e.to_dict() for e in events]})
