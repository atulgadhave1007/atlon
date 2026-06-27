import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import (
    ExpenseCategory, ExpenseClaim, ExpenseItem, TravelRequest,
    Asset, AssetCategory, AssetAssignment, ExpenseStatus
)
from app.utils.auth import require_auth
from app.utils.security import sanitize_string
import secrets, string

expense_bp = Blueprint("expense", __name__)


def _claim_number():
    return "EXP" + "".join(secrets.choice(string.digits) for _ in range(7))


# ── Expense Categories ────────────────────────────────────────────────────────

@expense_bp.route("/categories", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def list_categories():
    cats = ExpenseCategory.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).all()
    return jsonify({"categories": [c.to_dict() for c in cats]})


@expense_bp.route("/categories", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_category():
    data = request.get_json(silent=True) or {}
    cat = ExpenseCategory(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=sanitize_string(data.get("name", ""), 100),
        code=sanitize_string(data.get("code", ""), 20),
        description=sanitize_string(data.get("description", ""), 300),
        requires_receipt=bool(data.get("requires_receipt", True)),
        max_amount=float(data.get("max_amount")) if data.get("max_amount") else None,
        gl_code=sanitize_string(data.get("gl_code", ""), 30),
    )
    db.session.add(cat)
    db.session.commit()
    return jsonify({"category": cat.to_dict()}), 201


# ── Claims ────────────────────────────────────────────────────────────────────

@expense_bp.route("/claims", methods=["GET"])
@require_auth()
def list_claims():
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    q = ExpenseClaim.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if g.role == "employee":
        q = q.filter_by(employee_id=str(g.employee.id))
    elif employee_id:
        q = q.filter_by(employee_id=employee_id)
    if status:
        q = q.filter_by(status=status)
    claims = q.order_by(ExpenseClaim.created_at.desc()).all()
    return jsonify({"claims": [c.to_dict() for c in claims]})


@expense_bp.route("/claims", methods=["POST"])
@require_auth()
def create_claim():
    data = request.get_json(silent=True) or {}
    items_data = data.get("items", [])
    if not items_data:
        return jsonify({"error": "At least one expense item is required"}), 400

    total = sum(float(i.get("amount", 0)) for i in items_data)

    claim = ExpenseClaim(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=str(g.employee.id),
        claim_number=_claim_number(),
        title=sanitize_string(data.get("title", ""), 200),
        description=sanitize_string(data.get("description", ""), 500),
        total_amount=total,
        currency=data.get("currency", "INR"),
        status=ExpenseStatus.DRAFT,
    )
    db.session.add(claim)
    db.session.flush()

    for item in items_data:
        from datetime import date as ddate
        ei = ExpenseItem(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            claim_id=claim.id,
            category_id=item.get("category_id"),
            description=sanitize_string(item.get("description", ""), 300),
            expense_date=datetime.strptime(item["expense_date"], "%Y-%m-%d").date(),
            amount=float(item.get("amount", 0)),
            currency=item.get("currency", "INR"),
            receipt_url=item.get("receipt_url"),
            vendor=sanitize_string(item.get("vendor", ""), 200),
        )
        db.session.add(ei)

    db.session.commit()
    return jsonify({"claim": claim.to_dict()}), 201


@expense_bp.route("/claims/<claim_id>/submit", methods=["POST"])
@require_auth()
def submit_claim(claim_id):
    claim = ExpenseClaim.query.filter_by(
        id=claim_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if str(claim.employee_id) != str(g.employee.id) and g.role not in ("hr_admin",):
        return jsonify({"error": "Access denied"}), 403
    claim.status = ExpenseStatus.SUBMITTED
    claim.submitted_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "Claim submitted", "claim": claim.to_dict()})


@expense_bp.route("/claims/<claim_id>/approve", methods=["POST"])
@require_auth(roles=["hr_admin", "manager"])
def approve_claim(claim_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action", "approve")
    claim = ExpenseClaim.query.filter_by(
        id=claim_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    claim.approved_by_id = str(g.employee.id)
    claim.approved_at = datetime.now(timezone.utc)
    if action == "approve":
        claim.status = ExpenseStatus.APPROVED
        claim.approved_amount = float(data.get("approved_amount", claim.total_amount))
    else:
        claim.status = ExpenseStatus.REJECTED
        claim.rejection_reason = data.get("reason")
    db.session.commit()
    return jsonify({"message": f"Claim {action}d"})


# ── Assets ────────────────────────────────────────────────────────────────────

@expense_bp.route("/assets", methods=["GET"])
@require_auth(roles=["hr_admin"])
def list_assets():
    q = Asset.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    return jsonify({"assets": [a.to_dict() for a in q.all()]})


@expense_bp.route("/assets", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_asset():
    data = request.get_json(silent=True) or {}
    asset = Asset(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        asset_code=sanitize_string(data.get("asset_code", ""), 50),
        name=sanitize_string(data.get("name", ""), 200),
        category_id=data.get("category_id"),
        brand=sanitize_string(data.get("brand", ""), 100),
        model=sanitize_string(data.get("model", ""), 100),
        serial_number=sanitize_string(data.get("serial_number", ""), 100),
        purchase_cost=float(data.get("purchase_cost", 0)) if data.get("purchase_cost") else None,
        branch_id=data.get("branch_id"),
        status="available",
    )
    db.session.add(asset)
    db.session.commit()
    return jsonify({"asset": asset.to_dict()}), 201


@expense_bp.route("/assets/<asset_id>/assign", methods=["POST"])
@require_auth(roles=["hr_admin"])
def assign_asset(asset_id):
    data = request.get_json(silent=True) or {}
    asset = Asset.query.filter_by(
        id=asset_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    employee_id = data.get("employee_id")
    if not employee_id:
        return jsonify({"error": "employee_id is required"}), 400

    asset.assigned_to_id = employee_id
    asset.assigned_at = datetime.now(timezone.utc)
    asset.status = "assigned"

    assignment = AssetAssignment(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        asset_id=asset_id,
        employee_id=employee_id,
        assigned_at=datetime.now(timezone.utc),
        assigned_by_id=str(g.employee.id),
        condition_on_assign=data.get("condition", "good"),
    )
    db.session.add(assignment)
    db.session.commit()
    return jsonify({"message": "Asset assigned"})


# ── Travel ────────────────────────────────────────────────────────────────────

@expense_bp.route("/travel", methods=["GET"])
@require_auth()
def list_travel():
    q = TravelRequest.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if g.role == "employee":
        q = q.filter_by(employee_id=str(g.employee.id))
    return jsonify({"requests": [r.to_dict() for r in q.all()]})


@expense_bp.route("/travel", methods=["POST"])
@require_auth()
def create_travel():
    data = request.get_json(silent=True) or {}
    req = TravelRequest(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=str(g.employee.id),
        request_number="TRV" + "".join(secrets.choice(string.digits) for _ in range(6)),
        purpose=sanitize_string(data.get("purpose", ""), 300),
        from_city=sanitize_string(data.get("from_city", ""), 100),
        to_city=sanitize_string(data.get("to_city", ""), 100),
        departure_date=datetime.strptime(data["departure_date"], "%Y-%m-%d").date(),
        return_date=datetime.strptime(data["return_date"], "%Y-%m-%d").date(),
        travel_mode=data.get("travel_mode"),
        accommodation_required=bool(data.get("accommodation_required", False)),
        estimated_cost=float(data.get("estimated_cost", 0)) if data.get("estimated_cost") else None,
        status="pending",
    )
    db.session.add(req)
    db.session.commit()
    return jsonify({"request": req.to_dict()}), 201
