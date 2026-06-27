import uuid
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import (
    AppraisalCycle, Goal, PeerFeedback, OKRObjective, OKRKeyResult, OKRCheckIn,
    AppraisalCycleStatus, GoalStatus, Employee
)
from app.utils.auth import require_auth, log_action

performance_bp = Blueprint("performance", __name__)


@performance_bp.route("/cycles", methods=["GET"])
@require_auth()
def list_cycles():
    cycles = AppraisalCycle.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(AppraisalCycle.period_from.desc()).all()
    return jsonify({"cycles": [c.to_dict() for c in cycles]})


@performance_bp.route("/cycles", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_cycle():
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    cycle = AppraisalCycle(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=data.get("name", "").strip(),
        description=data.get("description"),
        period_from=datetime.strptime(data["period_from"], "%Y-%m-%d").date(),
        period_to=datetime.strptime(data["period_to"], "%Y-%m-%d").date(),
        status=AppraisalCycleStatus.DRAFT,
        include_360=bool(data.get("include_360", False)),
        rating_scale=int(data.get("rating_scale", 5)),
    )
    db.session.add(cycle)
    db.session.commit()
    return jsonify({"cycle": cycle.to_dict()}), 201


@performance_bp.route("/cycles/<cycle_id>/status", methods=["PATCH"])
@require_auth(roles=["hr_admin"])
def update_cycle_status(cycle_id):
    data = request.get_json(silent=True) or {}
    cycle = AppraisalCycle.query.filter_by(
        id=cycle_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    cycle.status = data.get("status", cycle.status)
    db.session.commit()
    return jsonify({"cycle": cycle.to_dict()})


@performance_bp.route("/my-goals", methods=["GET"])
@require_auth()
def my_goals():
    """Employee alias: always returns current employee's goals."""
    cycle_id = request.args.get("cycle_id")
    q = Goal.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    )
    if cycle_id:
        q = q.filter_by(cycle_id=cycle_id)
    return jsonify({"goals": [item.to_dict() for item in q.all()]})


@performance_bp.route("/appraisals/self", methods=["GET"])
@require_auth()
def appraisals_self():
    """Employee's own pending/in-progress appraisals."""
    cycles = AppraisalCycle.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(AppraisalCycle.created_at.desc()).all()
    result = []
    for c in cycles:
        goals = Goal.query.filter_by(
            tenant_id=g.tenant_id, cycle_id=c.id,
            employee_id=g.employee.id, is_deleted=False,
        ).all()
        if not goals:
            continue
        fy = f"FY {c.period_from.year}-{str(c.period_to.year)[2:]}" if c.period_from and c.period_to else None
        status_val = c.status.value if hasattr(c.status, "value") else str(c.status)
        result.append({
            "id": str(c.id), "financial_year": fy, "cycle_name": c.name,
            "review_type": "Annual", "status": status_val,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return jsonify({"appraisals": result})


@performance_bp.route("/appraisals/completed", methods=["GET"])
@require_auth()
def appraisals_completed():
    """Employee's completed appraisals."""
    cycles = AppraisalCycle.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(AppraisalCycle.created_at.desc()).all()
    result = []
    for c in cycles:
        status_val = c.status.value if hasattr(c.status, "value") else str(c.status)
        if status_val not in ("completed", "closed"):
            continue
        goals = Goal.query.filter_by(
            tenant_id=g.tenant_id, cycle_id=c.id,
            employee_id=g.employee.id, is_deleted=False,
        ).all()
        fy = f"FY {c.period_from.year}-{str(c.period_to.year)[2:]}" if c.period_from and c.period_to else None
        result.append({
            "id": str(c.id), "financial_year": fy, "cycle_name": c.name,
            "review_type": "Annual", "status": status_val,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return jsonify({"appraisals": result})


@performance_bp.route("/appraisals/request-approval", methods=["GET"])
@require_auth()
def appraisals_request_approval():
    """Employee's appraisal cycles available for requesting approval."""
    cycles = AppraisalCycle.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(AppraisalCycle.created_at.desc()).all()
    result = []
    for c in cycles:
        status_val = c.status.value if hasattr(c.status, "value") else str(c.status)
        if status_val not in ("active", "open"):
            continue
        goals = Goal.query.filter_by(
            tenant_id=g.tenant_id, cycle_id=c.id,
            employee_id=g.employee.id, is_deleted=False,
        ).all()
        if not goals:
            continue
        fy = f"FY {c.period_from.year}-{str(c.period_to.year)[2:]}" if c.period_from and c.period_to else None
        has_self_rating = all(go.self_rating is not None for go in goals)
        result.append({
            "id": str(c.id), "financial_year": fy, "cycle_name": c.name,
            "review_type": "Annual",
            "status": "pending_approval" if has_self_rating else "draft",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return jsonify({"requests": result})


@performance_bp.route("/appraisals/increment", methods=["GET"])
@require_auth()
def appraisals_increment():
    """Completed appraisal cycles eligible for increment processing."""
    cycles = AppraisalCycle.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(AppraisalCycle.created_at.desc()).all()
    result = []
    for c in cycles:
        status_val = c.status.value if hasattr(c.status, "value") else str(c.status)
        if status_val not in ("completed", "closed"):
            continue
        goals = Goal.query.filter_by(
            tenant_id=g.tenant_id, cycle_id=c.id,
            employee_id=g.employee.id, is_deleted=False,
        ).all()
        if not goals:
            continue
        result.append({
            "id": str(c.id),
            "cycle_date": c.period_to.isoformat() if c.period_to else None,
            "status": status_val,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return jsonify({"requests": result})


@performance_bp.route("/appraisals", methods=["GET"])
@require_auth()
def list_appraisals():
    """Employee-facing: list appraisal cycles with employee's goal completion status."""
    cycles = AppraisalCycle.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(AppraisalCycle.created_at.desc()).all()
    result = []
    for c in cycles:
        goals = Goal.query.filter_by(
            tenant_id=g.tenant_id,
            cycle_id=c.id,
            employee_id=g.employee.id,
            is_deleted=False,
        ).all()
        self_rating = sum(float(go.self_rating or 0) for go in goals)
        manager_rating = sum(float(go.manager_rating or 0) for go in goals)
        fy = None
        if c.period_from and c.period_to:
            fy = f"FY {c.period_from.year}-{str(c.period_to.year)[2:]}"
        result.append({
            "id": str(c.id),
            "name": c.name,
            "financial_year": fy,
            "review_type": "Annual",
            "period_start": c.period_from.isoformat() if c.period_from else None,
            "period_end": c.period_to.isoformat() if c.period_to else None,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "goal_count": len(goals),
            "self_rating": self_rating,
            "manager_rating": manager_rating,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "modified_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return jsonify({"appraisals": result})


@performance_bp.route("/kras", methods=["GET"])
@require_auth()
def list_kras():
    """Employee KRAs — goals with title/weightage/target."""
    q = Goal.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=g.employee.id,
        is_deleted=False,
    )
    items = q.all()
    result = []
    for g_item in items:
        fy = None
        if g_item.cycle_id:
            c = AppraisalCycle.query.get(g_item.cycle_id)
            if c and c.period_from and c.period_to:
                fy = f"FY {c.period_from.year}-{str(c.period_to.year)[2:]}"
        result.append({
            "id": str(g_item.id),
            "title": g_item.title,
            "weightage": float(g_item.weightage or 0),
            "target": g_item.target_value,
            "financial_year": fy,
        })
    return jsonify({"kras": result})


@performance_bp.route("/goals", methods=["GET"])
@require_auth()
def list_goals():
    cycle_id = request.args.get("cycle_id")
    employee_id = request.args.get("employee_id") or str(g.employee.id)
    if g.role == "employee":
        employee_id = str(g.employee.id)
    q = Goal.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if cycle_id:
        q = q.filter_by(cycle_id=cycle_id)
    if g.role in ("employee", "manager"):
        q = q.filter_by(employee_id=employee_id)
    return jsonify({"goals": [g_item.to_dict() for g_item in q.all()]})


@performance_bp.route("/goals", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin"])
def create_goal():
    data = request.get_json(silent=True) or {}
    goal = Goal(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        cycle_id=data.get("cycle_id"),
        employee_id=data.get("employee_id") or str(g.employee.id),
        title=data.get("title", "").strip(),
        description=data.get("description"),
        kpi_metric=data.get("kpi_metric"),
        target_value=data.get("target_value"),
        weightage=float(data.get("weightage", 0)),
        status=GoalStatus.DRAFT,
    )
    db.session.add(goal)
    db.session.commit()
    return jsonify({"goal": goal.to_dict()}), 201


@performance_bp.route("/goals/<goal_id>/rate", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin"])
def rate_goal(goal_id):
    data = request.get_json(silent=True) or {}
    goal = Goal.query.filter_by(id=goal_id, tenant_id=g.tenant_id, is_deleted=False).first_or_404()
    rater = data.get("rater_type", "self")
    if rater == "self":
        goal.self_rating = float(data.get("rating", 0))
        goal.self_remarks = data.get("remarks", "")
    elif rater == "manager":
        goal.manager_rating = float(data.get("rating", 0))
        goal.manager_remarks = data.get("remarks", "")
        goal.achieved_value = data.get("achieved_value")
    elif rater == "final" and g.role == "hr_admin":
        goal.final_rating = float(data.get("rating", 0))
        goal.final_remarks = data.get("remarks", "")
    db.session.commit()
    return jsonify({"goal": goal.to_dict()})


@performance_bp.route("/feedback/request", methods=["POST"])
@require_auth(roles=["employee", "manager", "hr_admin"])
def request_feedback():
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    cycle_id = data.get("cycle_id")
    reviewer_ids = data.get("reviewer_ids", [])
    subject_id = data.get("subject_employee_id") or str(g.employee.id)

    created = []
    for rid in reviewer_ids:
        fb = PeerFeedback(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            cycle_id=cycle_id,
            subject_employee_id=subject_id,
            reviewer_employee_id=rid,
            relationship_type=data.get("relationship_type", "peer"),
            is_anonymous=bool(data.get("is_anonymous", True)),
        )
        db.session.add(fb)
        created.append(str(fb.id))
    db.session.commit()
    return jsonify({"message": "Feedback requests sent", "ids": created}), 201


@performance_bp.route("/feedback/submit/<feedback_id>", methods=["POST"])
@require_auth()
def submit_feedback(feedback_id):
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    fb = PeerFeedback.query.filter_by(id=feedback_id, tenant_id=g.tenant_id).first_or_404()
    if str(fb.reviewer_employee_id) != str(g.employee.id):
        return jsonify({"error": "Not your feedback request"}), 403
    fb.responses = data.get("responses", {})
    fb.overall_rating = float(data.get("overall_rating", 0))
    fb.strengths = data.get("strengths", "")
    fb.improvement_areas = data.get("improvement_areas", "")
    fb.submitted_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "Feedback submitted"})


@performance_bp.route("/feedback/pending", methods=["GET"])
@require_auth()
def pending_feedback():
    feedbacks = PeerFeedback.query.filter_by(
        tenant_id=g.tenant_id,
        reviewer_employee_id=g.employee.id,
        is_deleted=False
    ).filter(PeerFeedback.submitted_at.is_(None)).all()
    return jsonify({"pending": [f.to_dict() for f in feedbacks]})


@performance_bp.route("/feedback/for/<emp_id>", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def feedback_for_employee(emp_id):
    cycle_id = request.args.get("cycle_id")
    q = PeerFeedback.query.filter_by(
        tenant_id=g.tenant_id, subject_employee_id=emp_id, is_deleted=False
    ).filter(PeerFeedback.submitted_at.isnot(None))
    if cycle_id:
        q = q.filter_by(cycle_id=cycle_id)
    feedbacks = q.all()
    result = [f.to_dict() for f in feedbacks]
    if feedbacks:
        ratings = [f.overall_rating for f in feedbacks if f.overall_rating]
        avg = sum(ratings) / len(ratings) if ratings else None
        return jsonify({"feedbacks": result, "average_rating": avg, "count": len(feedbacks)})
    return jsonify({"feedbacks": [], "average_rating": None, "count": 0})


# ── OKRs ──────────────────────────────────────────────────────────────────────

@performance_bp.route("/okr/objectives", methods=["GET"])
@require_auth()
def list_objectives():
    q = OKRObjective.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if g.role == "employee":
        q = q.filter_by(owner_id=g.employee.id)
    return jsonify({"objectives": [o.to_dict() for o in q.all()]})


@performance_bp.route("/okr/objectives", methods=["POST"])
@require_auth()
def create_objective():
    data = request.get_json(silent=True) or {}
    obj = OKRObjective(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        title=data.get("title", "").strip(),
        description=data.get("description"),
        owner_id=data.get("owner_id") or str(g.employee.id),
        quarter=data.get("quarter"),
        year=int(data.get("year", __import__("datetime").datetime.now().year)),
    )
    db.session.add(obj)
    db.session.commit()
    return jsonify({"objective": obj.to_dict()}), 201


@performance_bp.route("/okr/objectives/<obj_id>/key-results", methods=["POST"])
@require_auth()
def create_key_result(obj_id):
    data = request.get_json(silent=True) or {}
    kr = OKRKeyResult(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        objective_id=obj_id,
        title=data.get("title", "").strip(),
        target_value=float(data.get("target_value", 100)),
        current_value=float(data.get("current_value", 0)),
        unit=data.get("unit", "%"),
        owner_id=str(g.employee.id),
    )
    db.session.add(kr)
    db.session.commit()
    return jsonify({"key_result": kr.to_dict()}), 201


@performance_bp.route("/okr/key-results/<kr_id>/checkin", methods=["POST"])
@require_auth()
def checkin_kr(kr_id):
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    kr = OKRKeyResult.query.filter_by(id=kr_id, tenant_id=g.tenant_id).first_or_404()
    checkin = OKRCheckIn(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        key_result_id=kr_id,
        employee_id=str(g.employee.id),
        value=float(data.get("value", 0)),
        notes=data.get("notes"),
        confidence_level=data.get("confidence_level"),
    )
    kr.current_value = float(data.get("value", 0))
    if kr.target_value and kr.target_value != 0:
        kr.progress = min(100, (kr.current_value / float(kr.target_value)) * 100)
    db.session.add(checkin)
    db.session.commit()
    return jsonify({"key_result": kr.to_dict()})
