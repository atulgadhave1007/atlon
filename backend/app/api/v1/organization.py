import uuid
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import Department, Designation, Branch, CostCenter
from app.utils.auth import require_auth, log_action
from app.utils.security import sanitize_string

org_bp = Blueprint("organization", __name__)


# ── Departments ───────────────────────────────────────────────────────────────

@org_bp.route("/departments", methods=["GET"])
@require_auth()
def list_departments():
    depts = Department.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).order_by(Department.name).all()
    return jsonify({"departments": [d.to_dict() for d in depts]})


@org_bp.route("/departments", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_department():
    data = request.get_json(silent=True) or {}
    name = sanitize_string(data.get("name", ""), 200)
    if not name:
        return jsonify({"error": "Name is required"}), 400
    dept = Department(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=name,
        code=sanitize_string(data.get("code", ""), 20) or None,
        parent_id=data.get("parent_id"),
        description=sanitize_string(data.get("description", ""), 500) or None,
    )
    db.session.add(dept)
    db.session.commit()
    log_action("create_department", "department", dept.id)
    return jsonify({"department": dept.to_dict()}), 201


@org_bp.route("/departments/<dept_id>", methods=["PUT"])
@require_auth(roles=["hr_admin"])
def update_department(dept_id):
    dept = Department.query.filter_by(id=dept_id, tenant_id=g.tenant_id, is_deleted=False).first_or_404()
    data = request.get_json(silent=True) or {}
    for field in ["name", "code", "description", "parent_id", "head_employee_id", "is_active"]:
        if field in data:
            setattr(dept, field, data[field])
    db.session.commit()
    return jsonify({"department": dept.to_dict()})


@org_bp.route("/departments/<dept_id>", methods=["DELETE"])
@require_auth(roles=["hr_admin"])
def delete_department(dept_id):
    dept = Department.query.filter_by(id=dept_id, tenant_id=g.tenant_id, is_deleted=False).first_or_404()
    dept.soft_delete()
    db.session.commit()
    return jsonify({"message": "Department removed"})


# ── Designations ──────────────────────────────────────────────────────────────

@org_bp.route("/designations", methods=["GET"])
@require_auth()
def list_designations():
    desigs = Designation.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).order_by(Designation.level).all()
    return jsonify({"designations": [d.to_dict() for d in desigs]})


@org_bp.route("/designations", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_designation():
    data = request.get_json(silent=True) or {}
    name = sanitize_string(data.get("name", ""), 200)
    if not name:
        return jsonify({"error": "Name is required"}), 400
    desig = Designation(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=name,
        code=sanitize_string(data.get("code", ""), 20) or None,
        grade=sanitize_string(data.get("grade", ""), 20) or None,
        level=int(data.get("level", 1)),
        department_id=data.get("department_id"),
        description=sanitize_string(data.get("description", ""), 500) or None,
    )
    db.session.add(desig)
    db.session.commit()
    return jsonify({"designation": desig.to_dict()}), 201


# ── Branches ──────────────────────────────────────────────────────────────────

@org_bp.route("/branches", methods=["GET"])
@require_auth()
def list_branches():
    branches = Branch.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).order_by(Branch.name).all()
    return jsonify({"branches": [b.to_dict() for b in branches]})


@org_bp.route("/branches", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_branch():
    data = request.get_json(silent=True) or {}
    name = sanitize_string(data.get("name", ""), 200)
    if not name:
        return jsonify({"error": "Name is required"}), 400
    branch = Branch(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=name,
        code=sanitize_string(data.get("code", ""), 20) or None,
        address=sanitize_string(data.get("address", ""), 500) or None,
        city=sanitize_string(data.get("city", ""), 100) or None,
        state=sanitize_string(data.get("state", ""), 100) or None,
        country=sanitize_string(data.get("country", "India"), 50),
        pincode=sanitize_string(data.get("pincode", ""), 20) or None,
        phone=sanitize_string(data.get("phone", ""), 20) or None,
        email=sanitize_string(data.get("email", ""), 200) or None,
        is_head_office=bool(data.get("is_head_office", False)),
        geo_lat=sanitize_string(data.get("geo_lat", ""), 20) or None,
        geo_lng=sanitize_string(data.get("geo_lng", ""), 20) or None,
        geo_radius_meters=int(data.get("geo_radius_meters", 100)),
    )
    db.session.add(branch)
    db.session.commit()
    return jsonify({"branch": branch.to_dict()}), 201


@org_bp.route("/policies", methods=["GET"])
@require_auth()
def list_policies():
    """Return company policy documents grouped by category.
    Currently uses DocumentTemplate records tagged as policies.
    Returns structured categories with document lists.
    """
    from app.models import DocumentTemplate
    templates = DocumentTemplate.query.filter_by(
        tenant_id=g.tenant_id, is_active=True, is_deleted=False
    ).order_by(DocumentTemplate.type).all()

    cat_map = {}
    for t in templates:
        cat_name = (t.type or "General").replace("_", " ").title()
        if cat_name not in cat_map:
            cat_map[cat_name] = []
        cat_map[cat_name].append({
            "id": str(t.id),
            "name": t.name or cat_name,
            "url": None,
        })

    categories = [{"name": k, "documents": v} for k, v in cat_map.items()]

    if not categories:
        categories = [
            {"name": "HR Policies", "documents": []},
            {"name": "Leave Policy", "documents": []},
            {"name": "Code of Conduct", "documents": []},
        ]

    return jsonify({"categories": categories})


@org_bp.route("/cost-centers", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin"])
def list_cost_centers():
    ccs = CostCenter.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).all()
    return jsonify({"cost_centers": [c.to_dict() for c in ccs]})


@org_bp.route("/cost-centers", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_cost_center():
    data = request.get_json(silent=True) or {}
    cc = CostCenter(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        name=sanitize_string(data.get("name", ""), 200),
        code=sanitize_string(data.get("code", ""), 20),
        description=sanitize_string(data.get("description", ""), 500) or None,
    )
    db.session.add(cc)
    db.session.commit()
    return jsonify({"cost_center": cc.to_dict()}), 201
