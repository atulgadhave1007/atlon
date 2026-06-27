import uuid, secrets, string, json as _json_mod
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import (
    HelpTicket, TicketComment, TicketCategory, Announcement, AnnouncementAck, VisitorPass,
    TicketPriority, TicketStatus, Employee
)
from app.utils.auth import require_auth
from app.utils.security import sanitize_string

helpdesk_bp = Blueprint("helpdesk", __name__)


def _ticket_number():
    return "TKT" + "".join(secrets.choice(string.digits) for _ in range(7))


def _ticket_to_frontend(t):
    """Add subject/category/department aliases that the frontend expects."""
    d = t.to_dict()
    d["subject"] = d.get("title", "")
    # parse structured tags: ["category:Hardware", "dept:IT", "request_type:Log Ticket"]
    for tag in (d.get("tags") or []):
        if isinstance(tag, str) and ":" in tag:
            key, _, val = tag.partition(":")
            if key in ("category", "department", "request_type"):
                d[key] = val
    return d


def _idea_to_frontend(t):
    """Parse innovation fields stored as JSON in description."""
    d = t.to_dict()
    d["subject"] = d.get("title", "")
    meta = {}
    if t.description:
        try:
            meta = _json_mod.loads(t.description)
        except (ValueError, TypeError):
            meta = {"idea": t.description}
    d["idea"] = meta.get("idea", t.description or "")
    d["department"] = meta.get("department", "")
    d["current_state"] = meta.get("current_state", "")
    d["additional_thoughts"] = meta.get("additional_thoughts", "")
    d["impact"] = meta.get("impact", "")
    d["remark"] = ""
    return d


@helpdesk_bp.route("/categories", methods=["GET"])
@require_auth()
def list_categories():
    cats = TicketCategory.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).all()
    return jsonify({"categories": [c.to_dict() for c in cats]})


@helpdesk_bp.route("/my-tickets", methods=["GET"])
@require_auth()
def my_tickets():
    """Employee-facing alias: always returns only own tickets."""
    status = request.args.get("status")
    q = HelpTicket.query.filter_by(
        tenant_id=g.tenant_id,
        employee_id=str(g.employee.id),
        is_deleted=False,
    )
    if status:
        q = q.filter_by(status=status)
    tickets = q.order_by(HelpTicket.created_at.desc()).all()
    return jsonify({"tickets": [_ticket_to_frontend(t) for t in tickets]})


@helpdesk_bp.route("/tickets", methods=["GET"])
@require_auth()
def list_tickets():
    q = HelpTicket.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if g.role == "employee":
        q = q.filter_by(employee_id=str(g.employee.id))
    elif g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()] + [str(g.employee.id)]
        q = q.filter(HelpTicket.employee_id.in_(team_ids))
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status)
    tickets = q.order_by(HelpTicket.created_at.desc()).all()
    return jsonify({"tickets": [t.to_dict() for t in tickets]})


@helpdesk_bp.route("/tickets", methods=["POST"])
@require_auth()
def create_ticket():
    data = request.get_json(silent=True) or {}
    # Build tags: preserve any caller-supplied tags, then append structured metadata
    extra_tags = list(data.get("tags") or [])
    for key in ("category", "department", "request_type"):
        val = sanitize_string(data.get(key, ""), 100)
        if val:
            extra_tags.append(f"{key}:{val}")
    ticket = HelpTicket(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        ticket_number=_ticket_number(),
        employee_id=str(g.employee.id),
        category_id=data.get("category_id"),
        title=sanitize_string(data.get("title") or data.get("subject", ""), 300),
        description=sanitize_string(data.get("description", ""), 5000),
        priority=data.get("priority", TicketPriority.MEDIUM.value),
        status=TicketStatus.OPEN,
        tags=extra_tags,
        attachments=data.get("attachments", []),
    )

    cat = TicketCategory.query.get(data.get("category_id")) if data.get("category_id") else None
    if cat and cat.default_assignee_id:
        ticket.assigned_to_id = cat.default_assignee_id
        from datetime import timedelta
        ticket.due_at = datetime.now(timezone.utc) + timedelta(hours=cat.sla_hours or 24)

    db.session.add(ticket)
    db.session.commit()
    return jsonify({"ticket": ticket.to_dict()}), 201


@helpdesk_bp.route("/tickets/<ticket_id>", methods=["PATCH"])
@require_auth()
def update_ticket(ticket_id):
    ticket = HelpTicket.query.filter_by(
        id=ticket_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if g.role == "employee" and str(ticket.employee_id) != str(g.employee.id):
        return jsonify({"error": "Access denied"}), 403
    data = request.get_json(silent=True) or {}
    old_status = ticket.status
    if "status" in data:
        try:
            ticket.status = TicketStatus(data["status"])
        except ValueError:
            return jsonify({"error": "Invalid status"}), 400
        if ticket.status == TicketStatus.RESOLVED:
            ticket.resolved_at = datetime.now(timezone.utc)
        elif ticket.status == TicketStatus.CLOSED:
            ticket.closed_at = datetime.now(timezone.utc)
    if "priority" in data:
        try: ticket.priority = TicketPriority(data["priority"])
        except ValueError: pass
    if "title" in data: ticket.title = sanitize_string(data["title"], 300)
    if "description" in data: ticket.description = sanitize_string(data["description"], 5000)
    if "assigned_to_id" in data and g.role in ("hr_admin", "manager"):
        ticket.assigned_to_id = data["assigned_to_id"]
    if "resolution" in data and g.role in ("hr_admin", "manager"):
        ticket.resolution = data["resolution"]
    db.session.commit()

    # Notify employee when status changes to resolved or closed
    status_changed = ticket.status != old_status
    if status_changed and ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        owner = Employee.query.filter_by(id=ticket.employee_id, is_deleted=False).first()
        if owner and owner.work_email:
            from app.services.email_service import queue_email
            from app.models import Tenant
            tenant = Tenant.query.get(g.tenant_id)
            queue_email(
                owner.work_email,
                f"Your Ticket Has Been {ticket.status.value.capitalize()}",
                'email/ticket_update.html',
                {
                    'employee_name': owner.full_name,
                    'ticket_title': ticket.title,
                    'new_status': ticket.status.value,
                    'resolution': ticket.resolution or '',
                    'company_name': tenant.name if tenant else '',
                },
            )

    return jsonify({"ticket": ticket.to_dict()})


@helpdesk_bp.route("/innovations", methods=["GET"])
@require_auth()
def list_innovations():
    """List innovation tickets. HR/Managers see all; employees see their own."""
    q = HelpTicket.query.filter(
        HelpTicket.tenant_id == g.tenant_id,
        HelpTicket.is_deleted == False,
        HelpTicket.tags.contains(["innovation"]),
    )
    if g.role == "employee":
        q = q.filter_by(employee_id=str(g.employee.id))
    tickets = q.order_by(HelpTicket.created_at.desc()).all()
    return jsonify({"ideas": [_idea_to_frontend(t) for t in tickets]})


@helpdesk_bp.route("/innovations", methods=["POST"])
@require_auth()
def submit_innovation():
    data = request.get_json(silent=True) or {}
    department = sanitize_string(data.get("department", ""), 200)
    idea = sanitize_string(data.get("idea", ""), 2000)
    current_state = sanitize_string(data.get("current_state", ""), 2000)
    additional_thoughts = sanitize_string(data.get("additional_thoughts", ""), 2000)
    impact = sanitize_string(data.get("impact", ""), 2000)

    # Support legacy title/description fields too
    title = sanitize_string(data.get("title", ""), 300)
    legacy_desc = sanitize_string(data.get("description", ""), 5000)

    if not idea and not legacy_desc:
        return jsonify({"error": "idea is required"}), 400
    if not title:
        prefix = f"[{department}] " if department else ""
        title = (prefix + (idea or legacy_desc))[:300]

    if idea:
        description = _json_mod.dumps({
            "idea": idea, "department": department,
            "current_state": current_state,
            "additional_thoughts": additional_thoughts,
            "impact": impact,
        })
    else:
        description = legacy_desc

    ticket = HelpTicket(
        id=uuid.uuid4(), tenant_id=g.tenant_id,
        ticket_number=_ticket_number(),
        employee_id=str(g.employee.id),
        title=title, description=description,
        priority=TicketPriority.LOW,
        status=TicketStatus.OPEN,
        tags=["innovation"],
    )
    db.session.add(ticket)
    db.session.commit()
    return jsonify({"message": "Innovation idea submitted", "id": str(ticket.id)}), 201


@helpdesk_bp.route("/hr-connect", methods=["GET"])
@require_auth()
def list_hr_connect():
    """List HR-Connect messages. HR sees all; employees see their own."""
    q = HelpTicket.query.filter(
        HelpTicket.tenant_id == g.tenant_id,
        HelpTicket.is_deleted == False,
        HelpTicket.tags.contains(["hr-connect"]),
    )
    if g.role == "employee":
        q = q.filter_by(employee_id=str(g.employee.id))
    tickets = q.order_by(HelpTicket.created_at.desc()).all()
    return jsonify({"queries": [_ticket_to_frontend(t) for t in tickets]})


@helpdesk_bp.route("/hr-connect", methods=["POST"])
@require_auth()
def hr_connect():
    data = request.get_json(silent=True) or {}
    subject = sanitize_string(data.get("subject", ""), 300)
    message = sanitize_string(data.get("message") or data.get("description", ""), 5000)
    if not subject or not message:
        return jsonify({"error": "subject and message are required"}), 400
    ticket = HelpTicket(
        id=uuid.uuid4(), tenant_id=g.tenant_id,
        ticket_number=_ticket_number(),
        employee_id=str(g.employee.id),
        title=subject, description=message,
        priority=TicketPriority.MEDIUM,
        status=TicketStatus.OPEN,
        tags=["hr-connect"],
    )
    db.session.add(ticket)
    db.session.commit()
    return jsonify({"message": "Message sent to HR", "id": str(ticket.id)}), 201


@helpdesk_bp.route("/tickets/<ticket_id>", methods=["GET"])
@require_auth()
def get_ticket(ticket_id):
    ticket = HelpTicket.query.filter_by(
        id=ticket_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if g.role == "employee" and str(ticket.employee_id) != str(g.employee.id):
        return jsonify({"error": "Access denied"}), 403
    data = ticket.to_dict()
    data["comments"] = [c.to_dict() for c in ticket.comments]
    return jsonify(data)


@helpdesk_bp.route("/tickets/<ticket_id>/comment", methods=["POST"])
@require_auth()
def add_comment(ticket_id):
    ticket = HelpTicket.query.filter_by(
        id=ticket_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    data = request.get_json(silent=True) or {}
    comment = TicketComment(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        ticket_id=ticket_id,
        author_id=str(g.employee.id),
        comment=sanitize_string(data.get("comment", ""), 5000),
        is_internal=bool(data.get("is_internal", False)) and g.role in ("hr_admin", "manager"),
        attachments=data.get("attachments", []),
    )
    db.session.add(comment)
    if ticket.status == TicketStatus.RESOLVED:
        ticket.status = TicketStatus.REOPENED
    db.session.commit()
    return jsonify({"comment": comment.to_dict()}), 201


@helpdesk_bp.route("/tickets/<ticket_id>/resolve", methods=["POST"])
@require_auth(roles=["hr_admin", "manager"])
def resolve_ticket(ticket_id):
    data = request.get_json(silent=True) or {}
    ticket = HelpTicket.query.filter_by(
        id=ticket_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolution = sanitize_string(data.get("resolution", ""), 2000)
    db.session.commit()
    return jsonify({"message": "Ticket resolved", "ticket": ticket.to_dict()})


# ── Announcements ─────────────────────────────────────────────────────────────

@helpdesk_bp.route("/announcements", methods=["GET"])
@require_auth()
def list_announcements():
    q = Announcement.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc())
    announcements = q.all()
    return jsonify({"announcements": [a.to_dict() for a in announcements]})


@helpdesk_bp.route("/announcements", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_announcement():
    data = request.get_json(silent=True) or {}
    ann = Announcement(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        title=sanitize_string(data.get("title", ""), 300),
        content=sanitize_string(data.get("content", ""), 10000),
        type=data.get("type", "general"),
        priority=data.get("priority", "normal"),
        target_all=bool(data.get("target_all", True)),
        target_departments=data.get("target_departments", []),
        target_branches=data.get("target_branches", []),
        target_employees=data.get("target_employees", []),
        is_pinned=bool(data.get("is_pinned", False)),
        requires_acknowledgement=bool(data.get("requires_acknowledgement", False)),
        created_by_id=str(g.employee.id),
        attachment_url=data.get("attachment_url"),
    )
    db.session.add(ann)
    db.session.commit()
    return jsonify({"announcement": ann.to_dict()}), 201


@helpdesk_bp.route("/announcements/<ann_id>", methods=["DELETE"])
@require_auth(roles=["hr_admin"])
def delete_announcement(ann_id):
    ann = Announcement.query.filter_by(
        id=ann_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    ann.soft_delete()
    db.session.commit()
    return jsonify({"message": "Announcement removed"})


@helpdesk_bp.route("/announcements/<ann_id>/acknowledge", methods=["POST"])
@require_auth()
def acknowledge(ann_id):
    existing = AnnouncementAck.query.filter_by(
        tenant_id=g.tenant_id, announcement_id=ann_id, employee_id=str(g.employee.id)
    ).first()
    if not existing:
        ack = AnnouncementAck(
            id=uuid.uuid4(),
            tenant_id=g.tenant_id,
            announcement_id=ann_id,
            employee_id=str(g.employee.id),
        )
        db.session.add(ack)
        db.session.commit()
    return jsonify({"message": "Acknowledged"})


# ── Visitor Management ────────────────────────────────────────────────────────

@helpdesk_bp.route("/visitors", methods=["GET"])
@require_auth(roles=["hr_admin"])
def list_visitors():
    visitors = VisitorPass.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).order_by(VisitorPass.created_at.desc()).limit(100).all()
    return jsonify({"visitors": [v.to_dict() for v in visitors]})


@helpdesk_bp.route("/visitors", methods=["POST"])
@require_auth()
def create_visitor():
    data = request.get_json(silent=True) or {}
    visitor = VisitorPass(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        visitor_name=sanitize_string(data.get("name", ""), 200),
        visitor_company=sanitize_string(data.get("company", ""), 200),
        visitor_phone=sanitize_string(data.get("phone", ""), 20),
        visitor_email=sanitize_string(data.get("email", ""), 200),
        purpose=sanitize_string(data.get("purpose", ""), 500),
        host_employee_id=data.get("host_employee_id") or str(g.employee.id),
        branch_id=data.get("branch_id"),
        id_type=data.get("id_type"),
        id_number=sanitize_string(data.get("id_number", ""), 50),
        badge_number="VB" + "".join(secrets.choice(string.digits) for _ in range(5)),
        status="expected",
    )
    if data.get("expected_at"):
        visitor.expected_at = datetime.fromisoformat(data["expected_at"])
    db.session.add(visitor)
    db.session.commit()
    return jsonify({"visitor": visitor.to_dict()}), 201
