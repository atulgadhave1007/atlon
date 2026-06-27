from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import Tenant
from app.utils.auth import require_auth

tenant_bp = Blueprint("tenant", __name__)


@tenant_bp.route("/info/<slug>", methods=["GET"])
def get_tenant_info(slug):
    tenant = Tenant.query.filter_by(slug=slug, is_deleted=False).first()
    if not tenant:
        return jsonify({"error": "Company not found"}), 404
    return jsonify({
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "logo_url": tenant.logo_url,
        "bg_image_url": tenant.bg_image_url,
        "primary_color": tenant.primary_color or "#1e4db7",
        "country": tenant.country.value if tenant.country else "IN",
        "currency": tenant.currency,
        "timezone": tenant.timezone,
    })


@tenant_bp.route("/settings", methods=["GET"])
@require_auth(roles=["hr_admin"])
def get_settings():
    tenant = Tenant.query.get(g.tenant_id)
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    return jsonify(tenant.to_dict())


@tenant_bp.route("/settings", methods=["PUT"])
@require_auth(roles=["hr_admin"])
def update_settings():
    from app.utils.security import sanitize_string
    data = request.get_json(silent=True) or {}
    tenant = Tenant.query.get(g.tenant_id)
    allowed_fields = [
        "name", "legal_name", "logo_url", "primary_color",
        "address", "city", "state", "pincode", "phone", "email", "website",
        "gstin", "pan", "tan", "pf_number", "esi_number", "lwf_number",
        "timezone", "date_format", "fiscal_year_start", "currency",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(tenant, field, sanitize_string(str(data[field])) if data[field] else None)
    db.session.commit()
    return jsonify({"message": "Settings updated", "tenant": tenant.to_dict()})
