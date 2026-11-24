import uuid
from datetime import datetime, timezone, date
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import ExitRequest, ExitClearance, FnFSettlement, ExitType, ExitStatus, Employee
from app.utils.auth import require_auth, log_action
from app.utils.tenant_refs import reject_foreign_refs

exit_bp = Blueprint("exit", __name__)

DEFAULT_CLEARANCE_ITEMS = [
    "IT Assets Return",
    "ID Card / Access Card",
    "Finance / Accounts Clearance",
    "Library / Stationery",
    "Payroll (Loans/Advances)",
    "HR Clearance",
    "Manager Sign-off",
    "NOC from Legal",
]


@exit_bp.route("/initiate", methods=["POST"])
@require_auth(roles=["hr_admin", "employee"])
def initiate_exit():
    data = request.get_json(silent=True) or {}
    emp_id = data.get("employee_id") or str(g.employee.id)
    if g.role == "employee":
        emp_id = str(g.employee.id)

    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    _ref_err = reject_foreign_refs(data, {"handover_employee_id": "Employee"})
    if _ref_err:
        return _ref_err
    exit_req = ExitRequest(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=emp_id,
        exit_type=data.get("exit_type", ExitType.RESIGNATION.value),
        resignation_date=datetime.strptime(data["resignation_date"], "%Y-%m-%d").date() if data.get("resignation_date") else date.today(),
        last_working_date=datetime.strptime(data["last_working_date"], "%Y-%m-%d").date() if data.get("last_working_date") else None,
        notice_period_days=int(data.get("notice_period_days", 30)),
        reason=data.get("reason", "").strip(),
        remarks=data.get("remarks", ""),
        status=ExitStatus.INITIATED,
        initiated_by_id=g.employee.id,
        handover_employee_id=data.get("handover_employee_id"),
    )
    db.session.add(exit_req)
    db.session.flush()

    for item_name in DEFAULT_CLEARANCE_ITEMS:
        item = ExitClearance(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            exit_request_id=exit_req.id,
            item_name=item_name,
            status="pending",
            is_mandatory=True,
        )
        db.session.add(item)

    from app.models import EmployeeStatus
    emp.status = EmployeeStatus.ON_NOTICE
    db.session.commit()
    log_action("initiate_exit", "exit_request", exit_req.id)
    return jsonify({"message": "Exit initiated", "exit_request_id": str(exit_req.id)}), 201


@exit_bp.route("/requests", methods=["GET"])
@require_auth(roles=["hr_admin"])
def list_exit_requests():
    q = ExitRequest.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    reqs = q.order_by(ExitRequest.created_at.desc()).all()
    return jsonify({"exit_requests": [r.to_dict() for r in reqs]})


@exit_bp.route("/my-request", methods=["GET"])
@require_auth()
def my_exit_request():
    req = ExitRequest.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).order_by(ExitRequest.created_at.desc()).first()
    if not req:
        return jsonify({"exit_request": None})
    return jsonify({"exit_request": req.to_dict()})


@exit_bp.route("/my-clearance", methods=["GET"])
@require_auth()
def my_clearance():
    req = ExitRequest.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).order_by(ExitRequest.created_at.desc()).first()
    if not req:
        return jsonify({"clearance_items": []})
    items = ExitClearance.query.filter_by(
        tenant_id=g.tenant_id,
        exit_request_id=req.id,
        is_deleted=False,
    ).all()
    return jsonify({"clearance_items": [i.to_dict() for i in items]})


@exit_bp.route("/my-fnf", methods=["GET"])
@require_auth()
def my_fnf():
    req = ExitRequest.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).order_by(ExitRequest.created_at.desc()).first()
    if not req:
        return jsonify({"fnf": None})
    fnf = FnFSettlement.query.filter_by(
        exit_request_id=req.id, is_deleted=False
    ).first()
    return jsonify({"fnf": fnf.to_dict() if fnf else None})


@exit_bp.route("/interview", methods=["GET"])
@require_auth(roles=["employee", "hr_admin"])
def get_exit_interview():
    """Return exit interview form data — questions and any existing answers."""
    req = ExitRequest.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).order_by(ExitRequest.created_at.desc()).first()
    questions = [
        {"id": "q1", "text": "What is your primary reason for leaving?", "type": "text"},
        {"id": "q2", "text": "How would you rate your overall experience? (1-10)", "type": "rating"},
        {"id": "q3", "text": "How was your relationship with your manager?", "type": "text"},
        {"id": "q4", "text": "What did you enjoy most about working here?", "type": "text"},
        {"id": "q5", "text": "What could be improved in the organization?", "type": "text"},
        {"id": "q6", "text": "Would you recommend this organization to others?", "type": "yesno"},
        {"id": "q7", "text": "Any additional comments?", "type": "text"},
    ]
    return jsonify({
        "questions": questions,
        "already_submitted": req.exit_interview_done if req else False,
        "notes": req.exit_interview_notes if req else None,
    })


@exit_bp.route("/interview", methods=["POST"])
@require_auth(roles=["employee", "hr_admin"])
def submit_exit_interview():
    data = request.get_json(silent=True) or {}
    req = ExitRequest.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).order_by(ExitRequest.created_at.desc()).first()
    if not req:
        return jsonify({"error": "No exit request found"}), 404
    req.exit_interview_done = True
    req.exit_interview_notes = data.get("notes", "")
    db.session.commit()
    log_action("exit_interview", "exit_request", req.id)
    return jsonify({"message": "Exit interview submitted"})


@exit_bp.route("/<req_id>/withdraw", methods=["POST"])
@require_auth(roles=["employee"])
def withdraw_exit(req_id):
    req = ExitRequest.query.filter_by(
        id=req_id,
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    ).first_or_404()
    if req.status not in (ExitStatus.INITIATED, "initiated"):
        return jsonify({"error": "Cannot withdraw — exit request is already processed"}), 409
    req.status = ExitStatus.WITHDRAWN
    emp = Employee.query.get(req.employee_id)
    if emp:
        from app.models import EmployeeStatus
        emp.status = EmployeeStatus.ACTIVE
    db.session.commit()
    log_action("withdraw_exit", "exit_request", req.id)
    return jsonify({"message": "Resignation withdrawn"})


@exit_bp.route("/<req_id>/approve", methods=["POST"])
@require_auth(roles=["hr_admin"])
def approve_exit(req_id):
    data = request.get_json(silent=True) or {}
    req = ExitRequest.query.filter_by(
        id=req_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    action = data.get("action", "approve")
    if action == "approve":
        req.status = ExitStatus.APPROVED
        req.approved_by_id = g.employee.id
        req.approved_at = datetime.now(timezone.utc)
    else:
        req.status = ExitStatus.REJECTED
        req.rejection_reason = data.get("reason")
        emp = Employee.query.get(req.employee_id)
        if emp:
            from app.models import EmployeeStatus
            emp.status = EmployeeStatus.ACTIVE
    db.session.commit()
    return jsonify({"message": f"Exit {action}d"})


@exit_bp.route("/<req_id>/clearance", methods=["GET"])
@require_auth(roles=["hr_admin"])
def get_clearance(req_id):
    items = ExitClearance.query.filter_by(
        tenant_id=g.tenant_id, exit_request_id=req_id, is_deleted=False
    ).all()
    return jsonify({"clearance_items": [i.to_dict() for i in items]})


@exit_bp.route("/clearance/<item_id>/complete", methods=["POST"])
@require_auth(roles=["hr_admin"])
def complete_clearance(item_id):
    data = request.get_json(silent=True) or {}
    item = ExitClearance.query.filter_by(
        id=item_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    item.status = "completed"
    item.completed_at = datetime.now(timezone.utc)
    item.remarks = data.get("remarks", "")
    db.session.commit()
    return jsonify({"message": "Clearance item completed"})


@exit_bp.route("/<req_id>/fnf", methods=["POST"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def calculate_fnf(req_id):
    data = request.get_json(silent=True) or {}
    req = ExitRequest.query.filter_by(
        id=req_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    existing = FnFSettlement.query.filter_by(
        exit_request_id=req_id, is_deleted=False
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.flush()

    salary_amount = float(data.get("salary_amount", 0))
    leave_encash = float(data.get("leave_encashment_amount", 0))
    gratuity = float(data.get("gratuity_amount", 0))
    bonus = float(data.get("bonus_amount", 0))
    reimbursements = float(data.get("reimbursements", 0))
    other_earnings = float(data.get("other_earnings", 0))
    advance_recovery = float(data.get("advance_recovery", 0))
    notice_recovery = float(data.get("notice_pay_recovery", 0))
    tds = float(data.get("tds_on_fnf", 0))
    other_deductions = float(data.get("other_deductions", 0))

    gross = salary_amount + leave_encash + gratuity + bonus + reimbursements + other_earnings
    deductions = advance_recovery + notice_recovery + tds + other_deductions
    net_payable = gross - deductions

    fnf = FnFSettlement(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        exit_request_id=req_id,
        employee_id=req.employee_id,
        salary_days=float(data.get("salary_days", 0)),
        salary_amount=salary_amount,
        leave_encashment_days=float(data.get("leave_encashment_days", 0)),
        leave_encashment_amount=leave_encash,
        gratuity_amount=gratuity,
        bonus_amount=bonus,
        reimbursements=reimbursements,
        other_earnings=other_earnings,
        advance_recovery=advance_recovery,
        notice_pay_recovery=notice_recovery,
        tds_on_fnf=tds,
        other_deductions=other_deductions,
        net_payable=net_payable,
        status="draft",
        calculation_notes=data.get("notes", {}),
    )
    req.status = ExitStatus.FNF_PENDING
    db.session.add(fnf)
    db.session.commit()
    log_action("calculate_fnf", "fnf_settlement", fnf.id)
    return jsonify({"message": "FnF calculated", "fnf": fnf.to_dict()})


@exit_bp.route("/<req_id>/complete", methods=["POST"])
@require_auth(roles=["hr_admin"])
def complete_exit(req_id):
    req = ExitRequest.query.filter_by(
        id=req_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    req.status = ExitStatus.COMPLETED
    emp = Employee.query.get(req.employee_id)
    if emp:
        from app.models import EmployeeStatus
        emp.status = EmployeeStatus.EXITED
        emp.date_of_exit = req.last_working_date
        emp.is_active = False
    db.session.commit()
    log_action("complete_exit", "exit_request", req.id)
    return jsonify({"message": "Employee exit completed"})
