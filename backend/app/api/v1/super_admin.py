from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app.extensions import db, limiter
from app.models import Tenant, Plan, Employee, SuperAdmin, TenantStatus, PlanTier
from app.utils.auth import require_super_admin, log_action
from app.utils.security import is_valid_slug, is_valid_email, sanitize_string
import uuid
from datetime import datetime, timezone, timedelta

super_bp = Blueprint("super_admin", __name__)


@super_bp.route("/stats", methods=["GET"])
@require_super_admin
def stats():
    total_tenants = Tenant.query.filter_by(is_deleted=False).count()
    active_tenants = Tenant.query.filter_by(status=TenantStatus.ACTIVE, is_deleted=False).count()
    trial_tenants = Tenant.query.filter_by(status=TenantStatus.TRIAL, is_deleted=False).count()
    total_employees = Employee.query.filter_by(is_deleted=False).count()
    active_employees = Employee.query.filter_by(is_deleted=False, is_active=True).count()

    return jsonify({
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "trial_tenants": trial_tenants,
        "total_employees": total_employees,
        "active_employees": active_employees,
    })


@super_bp.route("/tenants", methods=["GET"])
@require_super_admin
def list_tenants():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    search = request.args.get("search", "")
    status = request.args.get("status")

    q = Tenant.query.filter_by(is_deleted=False)
    if search:
        q = q.filter(
            db.or_(Tenant.name.ilike(f"%{search}%"), Tenant.slug.ilike(f"%{search}%"))
        )
    if status:
        q = q.filter_by(status=status)

    pagination = q.order_by(Tenant.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "tenants": [t.to_dict() for t in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "page": page,
    })


@super_bp.route("/tenants", methods=["POST"])
@require_super_admin
def create_tenant():
    data = request.get_json(silent=True) or {}
    name = sanitize_string(data.get("name", ""), 200)
    slug = (data.get("slug") or "").strip().lower()
    country = data.get("country", "IN")
    email = (data.get("email") or "").strip().lower()
    plan_name = data.get("plan", "starter")
    admin_name = sanitize_string(data.get("admin_name", "HR Admin"), 200)
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_password = data.get("admin_password") or "HrAdmin@123"

    if not name or not slug:
        return jsonify({"error": "Name and slug are required"}), 400
    if not is_valid_slug(slug):
        return jsonify({"error": "Slug must be 3–63 chars, lowercase letters, digits and hyphens only. Cannot use reserved words."}), 400
    if Tenant.query.filter_by(slug=slug).first():
        return jsonify({"error": "This slug is already taken"}), 409
    if not is_valid_email(admin_email):
        return jsonify({"error": "Invalid admin email"}), 400

    plan = Plan.query.filter_by(name=plan_name, is_deleted=False).first()

    tenant = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        name=name,
        email=email,
        country=country,
        plan_id=plan.id if plan else None,
        status=TenantStatus.TRIAL,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        timezone=data.get("timezone", "Asia/Kolkata"),
        currency=data.get("currency", "INR"),
        fiscal_year_start=int(data.get("fiscal_year_start", 4)),
    )
    db.session.add(tenant)
    db.session.flush()

    from app.models import Department, Designation
    default_dept = Department(tenant_id=tenant.id, name="General", code="GEN")
    default_desig = Designation(tenant_id=tenant.id, name="Staff", code="STAFF", level=1)
    db.session.add(default_dept)
    db.session.add(default_desig)
    db.session.flush()

    from app.models.employee import Role
    admin_emp = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        employee_number="EMP001",
        first_name=admin_name.split()[0] if admin_name else "HR",
        last_name=admin_name.split()[-1] if len(admin_name.split()) > 1 else "Admin",
        work_email=admin_email,
        date_of_joining=datetime.now(timezone.utc).date(),
        department_id=default_dept.id,
        designation_id=default_desig.id,
        role=Role.HR_ADMIN,
        password_hash=Employee.hash_password(admin_password),
        force_password_change=True,
        is_active=True,
    )
    db.session.add(admin_emp)
    db.session.commit()
    log_action("create_tenant", "tenant", tenant.id)

    return jsonify({
        "message": "Tenant created successfully",
        "tenant": tenant.to_dict(),
        "admin_email": admin_email,
        "admin_password": admin_password,
    }), 201


@super_bp.route("/tenants/<tenant_id>/status", methods=["PATCH"])
@require_super_admin
def update_tenant_status(tenant_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in [s.value for s in TenantStatus]:
        return jsonify({"error": "Invalid status"}), 400
    tenant = Tenant.query.get_or_404(tenant_id)
    old_status = tenant.status
    tenant.status = status
    db.session.commit()
    log_action("update_tenant_status", "tenant", tenant.id,
               old_values={"status": old_status}, new_values={"status": status})
    return jsonify({"message": f"Tenant status updated to {status}"})


@super_bp.route("/plans", methods=["GET"])
@require_super_admin
def list_plans():
    plans = Plan.query.filter_by(is_deleted=False).all()
    return jsonify({"plans": [p.to_dict() for p in plans]})
