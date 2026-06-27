import hashlib
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, g
from app.extensions import db, limiter
from app.models import Employee, SuperAdmin, RefreshToken, Tenant
from app.utils.auth import (
    generate_access_token, generate_refresh_token, decode_token, require_auth
)
from app.utils.security import validate_password, verify_totp, generate_totp_secret, generate_totp_uri, generate_backup_codes
from app.utils.auth import log_action
import pyotp, qrcode, io, base64

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per 5 minutes")
def login():
    data = request.get_json(silent=True) or {}
    # Accept 'username' (employee_number or email) or legacy 'email' field
    username = (data.get("username") or data.get("email") or "").strip()
    password = data.get("password") or ""
    mfa_code = data.get("mfa_code")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Tenant resolution: subdomain middleware (g.tenant) → X-Tenant-Slug header → body slug
    tenant = getattr(g, "tenant", None)
    if not tenant:
        slug = request.headers.get("X-Tenant-Slug") or data.get("slug") or ""
        if slug:
            tenant = Tenant.query.filter_by(slug=slug.lower(), is_deleted=False).first()

    # Super admin login — when no tenant is resolved, try super admin by email
    if not tenant:
        sa = SuperAdmin.query.filter_by(email=username.lower(), is_deleted=False).first()
        if sa and sa.is_active and sa.check_password(password):
            if sa.mfa_enabled and not mfa_code:
                return jsonify({"mfa_required": True}), 200
            if sa.mfa_enabled and not verify_totp(sa.mfa_secret, mfa_code):
                return jsonify({"error": "Invalid MFA code"}), 401
            sa.last_login_at = datetime.now(timezone.utc)
            sa.last_login_ip = request.remote_addr
            db.session.commit()
            access = generate_access_token(str(sa.id), "super_admin", is_super=True)
            raw_refresh, token_record = generate_refresh_token(
                super_admin_id=str(sa.id), ip=request.remote_addr,
                device_info=request.headers.get("User-Agent", "")[:500]
            )
            db.session.commit()
            return jsonify({
                "access_token": access,
                "refresh_token": raw_refresh,
                "user": {"role": "super_admin", "name": sa.name, "email": sa.email},
            })
        return jsonify({"error": "Invalid credentials"}), 401

    # Tenant employee login — match by employee_number (uppercase) or work_email
    emp = Employee.query.filter(
        Employee.tenant_id == tenant.id,
        Employee.is_deleted == False,
        db.or_(
            db.func.lower(Employee.work_email) == username.lower(),
            Employee.employee_number == username.upper(),
        )
    ).first()

    if not emp:
        return jsonify({"error": "Invalid credentials"}), 401

    if emp.is_locked:
        return jsonify({"error": "Account locked due to multiple failed login attempts. Try again later."}), 403

    if not emp.check_password(password):
        emp.failed_login_attempts = (emp.failed_login_attempts or 0) + 1
        max_attempts = current_app.config.get("MAX_LOGIN_ATTEMPTS", 5)
        if emp.failed_login_attempts >= max_attempts:
            from datetime import timedelta
            lockout_mins = current_app.config.get("LOCKOUT_DURATION_MINUTES", 30)
            emp.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_mins)
        db.session.commit()
        log_action("login_failed", "employee", emp.id, result="failure",
                   error_message="Invalid password")
        return jsonify({"error": "Invalid credentials"}), 401

    if not emp.is_active:
        return jsonify({"error": "Account is inactive. Contact HR."}), 403

    if emp.mfa_enabled and not mfa_code:
        return jsonify({"mfa_required": True}), 200

    if emp.mfa_enabled and mfa_code:
        if not verify_totp(emp.mfa_secret, mfa_code):
            if mfa_code not in (emp.mfa_backup_codes or []):
                return jsonify({"error": "Invalid MFA code"}), 401
            codes = list(emp.mfa_backup_codes)
            codes.remove(mfa_code)
            emp.mfa_backup_codes = codes

    emp.failed_login_attempts = 0
    emp.locked_until = None
    emp.last_login_at = datetime.now(timezone.utc)
    emp.last_login_ip = request.remote_addr

    if emp.force_password_change:
        db.session.commit()
        access = generate_access_token(str(emp.id), emp.role.value, str(tenant.id))
        return jsonify({"force_password_change": True, "access_token": access})

    access = generate_access_token(str(emp.id), emp.role.value, str(tenant.id))
    raw_refresh, token_record = generate_refresh_token(
        employee_id=str(emp.id), tenant_id=str(tenant.id),
        ip=request.remote_addr,
        device_info=request.headers.get("User-Agent", "")[:500]
    )
    db.session.commit()
    log_action("login", "employee", emp.id)

    return jsonify({
        "access_token": access,
        "refresh_token": raw_refresh,
        "user": {
            "role": emp.role.value,
            "name": emp.full_name,
            "email": emp.work_email,
            "employee_id": str(emp.id),
            "tenant_slug": tenant.slug,
            "tenant_name": tenant.name,
            "requires_mfa_setup": emp.mfa_enabled is False and current_app.config.get("FEATURE_MFA"),
        },
    })


@auth_bp.route("/refresh", methods=["POST"])
@limiter.limit("60 per minute")
def refresh():
    data = request.get_json(silent=True) or {}
    raw_token = data.get("refresh_token")
    if not raw_token:
        return jsonify({"error": "Refresh token required"}), 400

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    record = RefreshToken.query.filter_by(token_hash=token_hash, is_revoked=False).first()

    if not record:
        return jsonify({"error": "Invalid or expired refresh token"}), 401
    if record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        record.is_revoked = True
        db.session.commit()
        return jsonify({"error": "Refresh token expired"}), 401

    record.last_used_at = datetime.now(timezone.utc)

    if record.employee_id:
        emp = Employee.query.get(record.employee_id)
        if not emp or not emp.is_active:
            return jsonify({"error": "User inactive"}), 403
        access = generate_access_token(str(emp.id), emp.role.value, str(emp.tenant_id))
        db.session.commit()
        return jsonify({"access_token": access})

    if record.super_admin_id:
        sa = SuperAdmin.query.get(record.super_admin_id)
        if not sa or not sa.is_active:
            return jsonify({"error": "User inactive"}), 403
        access = generate_access_token(str(sa.id), "super_admin", is_super=True)
        db.session.commit()
        return jsonify({"access_token": access})

    return jsonify({"error": "Invalid token"}), 401


@auth_bp.route("/logout", methods=["POST"])
@require_auth()
def logout():
    data = request.get_json(silent=True) or {}
    raw_token = data.get("refresh_token")
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        record = RefreshToken.query.filter_by(token_hash=token_hash).first()
        if record:
            record.is_revoked = True
            record.revoked_at = datetime.now(timezone.utc)
            db.session.commit()
    return jsonify({"message": "Logged out successfully"})


@auth_bp.route("/me", methods=["GET"])
@require_auth()
def me():
    emp = g.employee
    if not emp:
        sa = g.super_admin
        return jsonify({"id": str(sa.id), "name": sa.name, "email": sa.email, "role": "super_admin"})
    return jsonify({
        "id": str(emp.id),
        "name": emp.full_name,
        "email": emp.work_email,
        "role": emp.role.value,
        "tenant_id": str(emp.tenant_id),
        "employee_number": emp.employee_number,
        "photo_url": emp.photo_url,
        "designation": emp.designation.name if emp.designation else None,
        "department": emp.department.name if emp.department else None,
        "mfa_enabled": emp.mfa_enabled,
    })


@auth_bp.route("/change-password", methods=["POST"])
@require_auth()
def change_password():
    data = request.get_json(silent=True) or {}
    current_pw = data.get("current_password", "")
    new_pw = data.get("new_password", "")
    emp = g.employee
    if not emp:
        return jsonify({"error": "Not available for super admin here"}), 400

    if not emp.check_password(current_pw):
        return jsonify({"error": "Current password is incorrect"}), 400

    errors = validate_password(new_pw, current_app.config)
    if errors:
        return jsonify({"error": "Password does not meet policy", "details": errors}), 400

    history = list(emp.password_history or [])
    import bcrypt
    for old_hash in history[-current_app.config.get("PASSWORD_HISTORY_COUNT", 5):]:
        if bcrypt.checkpw(new_pw.encode(), old_hash.encode()):
            return jsonify({"error": "Password has been used recently. Choose a different password."}), 400

    new_hash = emp.hash_password(new_pw)
    history.append(emp.password_hash)
    emp.password_hash = new_hash
    emp.password_history = history[-10:]
    emp.password_changed_at = datetime.now(timezone.utc)
    emp.force_password_change = False
    db.session.commit()
    log_action("change_password", "employee", emp.id)
    return jsonify({"message": "Password changed successfully"})


@auth_bp.route("/mfa/setup", methods=["POST"])
@require_auth()
def mfa_setup():
    emp = g.employee
    if not emp:
        return jsonify({"error": "Not supported for super admin via this route"}), 400
    if emp.mfa_enabled:
        return jsonify({"error": "MFA already enabled"}), 400

    secret = generate_totp_secret()
    uri = generate_totp_uri(secret, emp.work_email)

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    emp.mfa_secret = secret
    db.session.commit()
    return jsonify({
        "secret": secret,
        "qr_code": f"data:image/png;base64,{qr_b64}",
        "uri": uri,
    })


@auth_bp.route("/mfa/verify", methods=["POST"])
@require_auth()
def mfa_verify():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "")
    emp = g.employee
    if not emp or not emp.mfa_secret:
        return jsonify({"error": "MFA not set up"}), 400

    if not verify_totp(emp.mfa_secret, code):
        return jsonify({"error": "Invalid code"}), 400

    backup = generate_backup_codes()
    emp.mfa_enabled = True
    emp.mfa_backup_codes = backup
    db.session.commit()
    log_action("enable_mfa", "employee", emp.id)
    return jsonify({"message": "MFA enabled", "backup_codes": backup})


@auth_bp.route("/mfa/disable", methods=["POST"])
@require_auth()
def mfa_disable():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "")
    password = data.get("password", "")
    emp = g.employee
    if not emp:
        return jsonify({"error": "Not supported here"}), 400
    if not emp.mfa_enabled:
        return jsonify({"error": "MFA is not enabled"}), 400
    if not emp.check_password(password):
        return jsonify({"error": "Invalid password"}), 400
    if not verify_totp(emp.mfa_secret, code):
        return jsonify({"error": "Invalid MFA code"}), 400

    emp.mfa_enabled = False
    emp.mfa_secret = None
    emp.mfa_backup_codes = []
    db.session.commit()
    log_action("disable_mfa", "employee", emp.id)
    return jsonify({"message": "MFA disabled"})
