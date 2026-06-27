import uuid, secrets, string
from datetime import datetime, timezone, date
from flask import Blueprint, request, jsonify, g, current_app
from app.extensions import db
from app.models import Subscription, Invoice, Plan, Tenant, BillingCycle, InvoiceStatus
from app.utils.auth import require_super_admin, require_auth

billing_bp = Blueprint("billing", __name__)


@billing_bp.route("/plans", methods=["GET"])
def public_plans():
    plans = Plan.query.filter_by(is_active=True, is_deleted=False).all()
    return jsonify({"plans": [p.to_dict() for p in plans]})


@billing_bp.route("/subscription", methods=["GET"])
@require_auth(roles=["hr_admin"])
def get_subscription():
    sub = Subscription.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).first()
    if not sub:
        return jsonify({"subscription": None})
    return jsonify({"subscription": sub.to_dict()})


@billing_bp.route("/subscription", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_subscription():
    data = request.get_json(silent=True) or {}
    plan_name = data.get("plan", "standard")
    billing_cycle = data.get("billing_cycle", "monthly")
    payment_gateway = data.get("payment_gateway", "razorpay")

    plan = Plan.query.filter_by(name=plan_name, is_deleted=False).first()
    if not plan:
        return jsonify({"error": "Plan not found"}), 404

    tenant = Tenant.query.get(g.tenant_id)
    from app.models import Employee
    emp_count = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).count()

    price_per_emp = float(plan.price_per_employee_inr if tenant.currency == "INR" else plan.price_per_employee_usd)
    amount = price_per_emp * emp_count
    if billing_cycle == "annual":
        amount = amount * 12 * 0.9

    existing = Subscription.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).first()
    if existing:
        existing.plan_id = plan.id
        existing.billing_cycle = billing_cycle
        existing.amount_per_period = amount
        existing.employee_count_billed = emp_count
        sub = existing
    else:
        sub = Subscription(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            plan_id=plan.id,
            billing_cycle=billing_cycle,
            status="active",
            employee_count_billed=emp_count,
            amount_per_period=amount,
            currency=tenant.currency or "INR",
            current_period_start=date.today(),
            payment_gateway=payment_gateway,
        )
        db.session.add(sub)

    inv_number = "INV-" + datetime.now().strftime("%Y%m") + "-" + "".join(secrets.choice(string.digits) for _ in range(5))
    invoice = Invoice(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        subscription_id=sub.id,
        invoice_number=inv_number,
        status=InvoiceStatus.SENT,
        employee_count=emp_count,
        subtotal=amount,
        tax_amount=amount * 0.18,
        total_amount=amount + (amount * 0.18),
        currency=tenant.currency or "INR",
        due_date=date.today(),
        line_items=[{"description": f"{plan.display_name} plan - {emp_count} employees", "amount": amount}],
    )
    db.session.add(invoice)
    db.session.commit()

    return jsonify({
        "message": "Subscription created",
        "subscription": sub.to_dict(),
        "invoice": invoice.to_dict(),
        "payment_due": float(invoice.total_amount),
    }), 201


@billing_bp.route("/invoices", methods=["GET"])
@require_auth(roles=["hr_admin"])
def list_invoices():
    invoices = Invoice.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(Invoice.created_at.desc()).all()
    return jsonify({"invoices": [i.to_dict() for i in invoices]})


@billing_bp.route("/invoices/<inv_id>/paid", methods=["POST"])
@require_super_admin
def mark_paid(inv_id):
    data = request.get_json(silent=True) or {}
    invoice = Invoice.query.filter_by(id=inv_id, is_deleted=False).first_or_404()
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.now(timezone.utc)
    invoice.payment_reference = data.get("reference")
    invoice.payment_gateway = data.get("gateway")
    sub = Subscription.query.get(invoice.subscription_id)
    if sub:
        sub.status = "active"
    db.session.commit()
    return jsonify({"message": "Invoice marked as paid"})


@billing_bp.route("/signup", methods=["POST"])
def self_signup():
    """Self-serve signup — creates tenant + admin + trial subscription."""
    data = request.get_json(silent=True) or {}
    from app.utils.security import is_valid_slug, is_valid_email, validate_password, sanitize_string
    from app.models import PlanTier, TenantStatus, EmployeeStatus, Role, Department, Designation

    company_name = sanitize_string(data.get("company_name", ""), 200)
    slug = (data.get("slug") or "").strip().lower()
    admin_name = sanitize_string(data.get("admin_name", ""), 200)
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_password = data.get("password", "")
    country = data.get("country", "IN")

    if not company_name or not slug or not admin_email or not admin_password:
        return jsonify({"error": "company_name, slug, admin_email and password are required"}), 400
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid slug. Use 3-63 lowercase letters, digits and hyphens."}), 400
    if Tenant.query.filter_by(slug=slug).first():
        return jsonify({"error": "This company slug is already taken"}), 409
    if not is_valid_email(admin_email):
        return jsonify({"error": "Invalid email address"}), 400

    pw_errors = validate_password(admin_password)
    if pw_errors:
        return jsonify({"error": "Password does not meet policy", "details": pw_errors}), 400

    starter_plan = Plan.query.filter_by(name="starter", is_deleted=False).first()

    from datetime import timedelta
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        name=company_name,
        email=admin_email,
        country=country,
        plan_id=starter_plan.id if starter_plan else None,
        status=TenantStatus.TRIAL,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        currency="INR" if country == "IN" else ("AED" if country == "AE" else "USD"),
    )
    db.session.add(tenant)
    db.session.flush()

    default_dept = Department(id=uuid.uuid4(), tenant_id=tenant.id, name="General", code="GEN")
    default_desig = Designation(id=uuid.uuid4(), tenant_id=tenant.id, name="Staff", code="STAFF", level=1)
    db.session.add(default_dept)
    db.session.add(default_desig)
    db.session.flush()

    from app.models import Employee as EmpModel
    name_parts = admin_name.split() if admin_name else ["Admin"]
    admin = EmpModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        employee_number="EMP001",
        first_name=name_parts[0],
        last_name=name_parts[-1] if len(name_parts) > 1 else "User",
        work_email=admin_email,
        date_of_joining=date.today(),
        department_id=default_dept.id,
        designation_id=default_desig.id,
        role=Role.HR_ADMIN,
        status=EmployeeStatus.ACTIVE,
        password_hash=EmpModel.hash_password(admin_password),
        force_password_change=False,
        is_active=True,
    )
    db.session.add(admin)

    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_id=starter_plan.id if starter_plan else None,
        billing_cycle=BillingCycle.MONTHLY,
        status="trialing",
        employee_count_billed=0,
        amount_per_period=0,
        currency=tenant.currency,
        trial_start=date.today(),
        trial_end=(datetime.now(timezone.utc) + timedelta(days=14)).date(),
    )
    db.session.add(sub)
    db.session.commit()

    return jsonify({
        "message": "Welcome to Atlon HRMS! Your 14-day trial has started.",
        "tenant_slug": slug,
        "portal_url": f"https://{slug}.atlon.in",
        "admin_email": admin_email,
    }), 201
