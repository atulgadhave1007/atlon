import uuid
import hashlib
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, Tuple
import jwt
from flask import request, g, current_app
from app.extensions import db
from app.models import Employee, SuperAdmin, RefreshToken, AuditLog, Role


def _now():
    return datetime.now(timezone.utc)


def generate_access_token(subject_id: str, role: str, tenant_id: Optional[str] = None,
                           is_super: bool = False) -> str:
    payload = {
        "sub": subject_id,
        "role": role,
        "iat": _now(),
        "exp": _now() + current_app.config["JWT_ACCESS_EXPIRES"],
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    if is_super:
        payload["super"] = True
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def generate_refresh_token(employee_id: Optional[str] = None,
                            super_admin_id: Optional[str] = None,
                            tenant_id: Optional[str] = None,
                            ip: Optional[str] = None,
                            device_info: Optional[str] = None) -> Tuple[str, RefreshToken]:
    raw = str(uuid.uuid4())
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires = _now() + current_app.config["JWT_REFRESH_EXPIRES"]

    record = RefreshToken(
        employee_id=employee_id,
        super_admin_id=super_admin_id,
        tenant_id=tenant_id,
        token_hash=token_hash,
        ip_address=ip,
        device_info=device_info,
        expires_at=expires,
    )
    db.session.add(record)
    return raw, record


def decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config["JWT_SECRET"], algorithms=["HS256"])


def get_bearer_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    return None


def require_auth(roles: Optional[list] = None):
    """Decorator — injects g.employee and g.tenant_id. Optionally restricts to roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = get_bearer_token()
            if not token:
                return {"error": "Authentication required"}, 401
            try:
                payload = decode_token(token)
            except jwt.ExpiredSignatureError:
                return {"error": "Token expired"}, 401
            except jwt.InvalidTokenError:
                return {"error": "Invalid token"}, 401

            if payload.get("super"):
                g.super_admin = SuperAdmin.query.get(payload["sub"])
                g.employee = None
                g.tenant_id = None
                g.role = "super_admin"
            else:
                emp = Employee.query.filter_by(
                    id=payload["sub"],
                    is_deleted=False,
                    is_active=True
                ).first()
                if not emp:
                    return {"error": "User not found or inactive"}, 401
                if emp.is_locked:
                    return {"error": "Account temporarily locked"}, 403
                g.employee = emp
                g.tenant_id = str(emp.tenant_id)
                g.role = emp.role.value
                g.super_admin = None

            if roles and g.role not in roles + ["super_admin"]:
                return {"error": "Insufficient permissions"}, 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_super_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = get_bearer_token()
        if not token:
            return {"error": "Authentication required"}, 401
        try:
            payload = decode_token(token)
        except jwt.InvalidTokenError:
            return {"error": "Invalid token"}, 401
        if not payload.get("super"):
            return {"error": "Super admin access required"}, 403
        g.super_admin = SuperAdmin.query.get(payload["sub"])
        if not g.super_admin or not g.super_admin.is_active:
            return {"error": "Super admin not found or inactive"}, 403
        g.employee = None
        g.tenant_id = None
        g.role = "super_admin"
        return fn(*args, **kwargs)
    return wrapper


def get_tenant_id() -> Optional[str]:
    """Extract tenant_id from JWT or subdomain header."""
    if hasattr(g, "tenant_id") and g.tenant_id:
        return g.tenant_id
    host = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Forwarded-Host", "")
    if host:
        slug = host.split(".")[0]
        from app.models import Tenant
        t = Tenant.query.filter_by(slug=slug, is_deleted=False).first()
        if t:
            return str(t.id)
    return None


def log_action(action: str, entity_type: str = None, entity_id=None,
               old_values: dict = None, new_values: dict = None, result: str = "success",
               error_message: str = None):
    try:
        actor_id = str(g.employee.id) if hasattr(g, "employee") and g.employee else None
        actor_email = g.employee.work_email if hasattr(g, "employee") and g.employee else None
        actor_role = g.role if hasattr(g, "role") else None
        tenant_id = get_tenant_id()

        log = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_email=actor_email,
            actor_role=actor_role,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            old_values=old_values,
            new_values=new_values,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:500],
            result=result,
            error_message=error_message,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass
