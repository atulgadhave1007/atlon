import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import Notification, NotificationConfig, AuditLog
from app.utils.auth import require_auth

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("", methods=["GET"])
@require_auth()
def list_notifications():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    unread_only = request.args.get("unread") == "true"

    q = Notification.query.filter_by(
        tenant_id=g.tenant_id, employee_id=str(g.employee.id), is_deleted=False
    )
    if unread_only:
        q = q.filter_by(is_read=False)

    pagination = q.order_by(Notification.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    unread_count = Notification.query.filter_by(
        tenant_id=g.tenant_id, employee_id=str(g.employee.id), is_read=False, is_deleted=False
    ).count()

    return jsonify({
        "notifications": [n.to_dict() for n in pagination.items],
        "total": pagination.total,
        "unread_count": unread_count,
        "page": page,
    })


@notifications_bp.route("/mark-read", methods=["POST"])
@require_auth()
def mark_read():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")

    q = Notification.query.filter_by(
        tenant_id=g.tenant_id, employee_id=str(g.employee.id), is_deleted=False
    )
    if ids:
        q = q.filter(Notification.id.in_(ids))
    else:
        q = q.filter_by(is_read=False)

    now = datetime.now(timezone.utc)
    updated = 0
    for n in q.all():
        n.is_read = True
        n.read_at = now
        updated += 1

    db.session.commit()
    return jsonify({"message": f"{updated} notifications marked as read"})


@notifications_bp.route("/config", methods=["GET"])
@require_auth(roles=["hr_admin"])
def get_config():
    configs = NotificationConfig.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).all()
    return jsonify({"configs": [c.to_dict() for c in configs]})


@notifications_bp.route("/config", methods=["POST"])
@require_auth(roles=["hr_admin"])
def update_config():
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type")
    if not event_type:
        return jsonify({"error": "event_type is required"}), 400

    config = NotificationConfig.query.filter_by(
        tenant_id=g.tenant_id, event_type=event_type, is_deleted=False
    ).first()

    if not config:
        config = NotificationConfig(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            event_type=event_type,
        )
        db.session.add(config)

    for field in ["is_inapp_enabled", "is_email_enabled", "is_whatsapp_enabled",
                  "is_sms_enabled", "is_push_enabled", "additional_recipients"]:
        if field in data:
            setattr(config, field, data[field])

    db.session.commit()
    return jsonify({"config": config.to_dict()})


@notifications_bp.route("/test", methods=["POST"])
@require_auth(roles=["hr_admin"])
def test_notification():
    data = request.get_json(silent=True) or {}
    channel = data.get("channel", "inapp")
    emp = g.employee

    if channel == "inapp":
        notif = Notification(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            employee_id=str(emp.id),
            title="Test Notification",
            body="This is a test notification from Atlon HRMS.",
            type="test",
            channel="inapp",
        )
        db.session.add(notif)
        db.session.commit()
        return jsonify({"message": "In-app notification sent"})

    elif channel == "email":
        from app.utils.notifications import send_email
        try:
            send_email(
                to=emp.work_email,
                subject="Test Email — Atlon HRMS",
                body=f"Hello {emp.full_name},\n\nThis is a test email from Atlon HRMS.\n\nRegards,\nAtlon HRMS Team",
            )
            return jsonify({"message": "Email sent"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif channel == "whatsapp":
        phone = emp.personal_phone or emp.work_phone
        if not phone:
            return jsonify({"error": "No phone number on file"}), 400
        from app.utils.notifications import send_whatsapp
        try:
            send_whatsapp(phone, f"Hello {emp.first_name}! This is a test message from Atlon HRMS.")
            return jsonify({"message": "WhatsApp message sent"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Unknown channel"}), 400


@notifications_bp.route("/audit-log", methods=["GET"])
@require_auth(roles=["hr_admin"])
def audit_log():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    entity_type = request.args.get("entity_type")
    actor_id = request.args.get("actor_id")

    q = AuditLog.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if entity_type:
        q = q.filter_by(entity_type=entity_type)
    if actor_id:
        q = q.filter_by(actor_id=actor_id)

    pagination = q.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "logs": [l.to_dict() for l in pagination.items],
        "total": pagination.total,
        "page": page,
    })
