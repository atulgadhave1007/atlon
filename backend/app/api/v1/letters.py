import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g, send_file
import io
from app.extensions import db
from app.models import Employee, GeneratedDocument, DocumentTemplate
from app.utils.auth import require_auth, log_action

letters_bp = Blueprint("letters", __name__)


def _get_or_create_template(tenant_id: str, doc_type: str) -> str:
    """Returns the letter content template."""
    tmpl = DocumentTemplate.query.filter_by(
        tenant_id=tenant_id, type=doc_type, is_active=True, is_deleted=False
    ).first()
    if tmpl:
        return tmpl.content
    return _default_template(doc_type)


def _default_template(doc_type: str) -> str:
    templates = {
        "offer": """
<h2>OFFER LETTER</h2>
<p>Date: {{date}}</p>
<p>Dear {{candidate_name}},</p>
<p>We are pleased to offer you the position of <strong>{{designation}}</strong> at <strong>{{company_name}}</strong> with an annual CTC of <strong>{{ctc}}</strong>.</p>
<p>Your date of joining is {{joining_date}}.</p>
<p>This offer is subject to successful completion of background verification.</p>
<p>Regards,<br>{{hr_name}}<br>HR Department</p>
""",
        "experience": """
<h2>EXPERIENCE CERTIFICATE</h2>
<p>Date: {{date}}</p>
<p>To Whom It May Concern,</p>
<p>This is to certify that <strong>{{name}}</strong> (Emp. No. {{employee_number}}) was employed with us as <strong>{{designation}}</strong> in the <strong>{{department}}</strong> department from <strong>{{joining_date}}</strong> to <strong>{{exit_date}}</strong>.</p>
<p>During this period, {{pronoun}} conducted {{pronoun_self}} with diligence and integrity.</p>
<p>We wish {{pronoun}} the very best in future endeavours.</p>
<p>Regards,<br>{{hr_name}}<br>HR Department<br>{{company_name}}</p>
""",
        "salary_certificate": """
<h2>SALARY CERTIFICATE</h2>
<p>Date: {{date}}</p>
<p>To Whom It May Concern,</p>
<p>This is to certify that <strong>{{name}}</strong> is employed with us as <strong>{{designation}}</strong> since <strong>{{joining_date}}</strong>.</p>
<p>{{pronoun}} draws a gross monthly salary of <strong>{{gross_salary}}</strong> ({{currency}}).</p>
<p>This certificate is issued upon the request of the employee for their personal use.</p>
<p>Regards,<br>{{hr_name}}<br>HR Department<br>{{company_name}}</p>
""",
        "appraisal": """
<h2>APPRAISAL / INCREMENT LETTER</h2>
<p>Date: {{date}}</p>
<p>Dear {{name}},</p>
<p>We are pleased to inform you that based on your performance review for the period ending {{review_period}}, your annual CTC has been revised to <strong>{{new_ctc}}</strong> effective from <strong>{{effective_date}}</strong>.</p>
<p>We appreciate your contributions and look forward to your continued success.</p>
<p>Regards,<br>{{hr_name}}<br>HR Department</p>
""",
    }
    return templates.get(doc_type, "<p>Letter content not configured.</p>")


def _generate_pdf(html_content: str, title: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(html_content.replace("\n", "<br/>"), styles["Normal"])]
    doc.build(story)
    return buf.getvalue()


@letters_bp.route("/request", methods=["POST"])
@require_auth()
def request_letter():
    """Employee self-service: request a letter from HR."""
    data = request.get_json(silent=True) or {}
    letter_type = data.get("letter_type", "").strip()
    valid_types = {"experience", "salary_certificate", "bonafide", "noc", "relieving", "appointment"}
    if letter_type not in valid_types:
        return jsonify({"error": f"letter_type must be one of: {', '.join(sorted(valid_types))}"}), 400

    import json
    emp = g.employee
    request_meta = json.dumps({
        "status": "requested",
        "requested_by": str(emp.id),
        "letter_type": letter_type,
        "remarks": data.get("remarks", ""),
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })

    type_label = letter_type.replace("_", " ").title()
    doc = GeneratedDocument(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_id=str(emp.id),
        document_type=letter_type,
        title=f"REQUEST: {type_label} - {emp.full_name}",
        generated_by_id=str(emp.id),
        content_snapshot=request_meta,
    )
    db.session.add(doc)
    db.session.commit()
    return jsonify({
        "id": str(doc.id),
        "message": f"{type_label} request submitted. HR will process it shortly.",
        "status": "requested",
    }), 201


@letters_bp.route("/my-requests", methods=["GET"])
@require_auth()
def my_letter_requests():
    """Employee's own letter request history."""
    import json
    docs = GeneratedDocument.query.filter_by(
        tenant_id=g.tenant_id, employee_id=str(g.employee.id), is_deleted=False
    ).order_by(GeneratedDocument.created_at.desc()).all()
    result = []
    for doc in docs:
        meta = {}
        if doc.content_snapshot:
            try: meta = json.loads(doc.content_snapshot)
            except Exception: pass
        result.append({
            "id": str(doc.id),
            "document_type": doc.document_type,
            "type": doc.document_type,
            "letter_type": doc.document_type,
            "title": doc.title,
            "status": meta.get("status", "generated" if doc.pdf_url else "requested"),
            "pdf_url": doc.pdf_url,
            "url": doc.pdf_url,
            "requested_at": doc.created_at.isoformat() if doc.created_at else None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "requested_by": g.employee.full_name,
        })
    return jsonify({"letters": result})


@letters_bp.route("/offer", methods=["POST"])
@require_auth(roles=["hr_admin"])
def offer_letter():
    data = request.get_json(silent=True) or {}
    content = _get_or_create_template(g.tenant_id, "offer")
    from app.models import Tenant
    tenant = Tenant.query.get(g.tenant_id)

    filled = content.replace("{{date}}", datetime.now().strftime("%d %B %Y"))
    filled = filled.replace("{{candidate_name}}", data.get("candidate_name", ""))
    filled = filled.replace("{{designation}}", data.get("designation", ""))
    filled = filled.replace("{{company_name}}", tenant.name if tenant else "")
    filled = filled.replace("{{ctc}}", str(data.get("ctc", "")))
    filled = filled.replace("{{joining_date}}", data.get("joining_date", ""))
    filled = filled.replace("{{hr_name}}", g.employee.full_name)

    pdf_bytes = _generate_pdf(filled, "Offer Letter")

    doc = GeneratedDocument(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        document_type="offer",
        title=f"Offer Letter - {data.get('candidate_name', '')}",
        generated_by_id=g.employee.id,
        content_snapshot=filled,
    )
    db.session.add(doc)
    db.session.commit()
    log_action("generate_offer_letter", "document", doc.id)

    response = send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"offer_letter_{data.get('candidate_name', 'candidate').replace(' ', '_')}.pdf"
    )
    return response


@letters_bp.route("/experience/<emp_id>", methods=["GET"])
@require_auth(roles=["hr_admin"])
def experience_letter(emp_id):
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    from app.models import Tenant
    tenant = Tenant.query.get(g.tenant_id)

    content = _get_or_create_template(g.tenant_id, "experience")
    pronoun = "she" if emp.gender and emp.gender.value == "female" else "he"
    filled = content.replace("{{date}}", datetime.now().strftime("%d %B %Y"))
    filled = filled.replace("{{name}}", emp.full_name)
    filled = filled.replace("{{employee_number}}", emp.employee_number or "")
    filled = filled.replace("{{designation}}", emp.designation.name if emp.designation else "")
    filled = filled.replace("{{department}}", emp.department.name if emp.department else "")
    filled = filled.replace("{{joining_date}}", emp.date_of_joining.strftime("%d %B %Y") if emp.date_of_joining else "")
    filled = filled.replace("{{exit_date}}", emp.date_of_exit.strftime("%d %B %Y") if emp.date_of_exit else "present")
    filled = filled.replace("{{pronoun}}", pronoun.capitalize())
    filled = filled.replace("{{pronoun_self}}", pronoun + "self")
    filled = filled.replace("{{hr_name}}", g.employee.full_name)
    filled = filled.replace("{{company_name}}", tenant.name if tenant else "")

    pdf_bytes = _generate_pdf(filled, "Experience Certificate")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"experience_letter_{emp.employee_number}.pdf"
    )


@letters_bp.route("/salary-certificate/<emp_id>", methods=["GET"])
@require_auth(roles=["hr_admin"])
def salary_certificate(emp_id):
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    from app.models import EmployeeSalary, Tenant
    salary = EmployeeSalary.query.filter_by(
        tenant_id=g.tenant_id, employee_id=emp_id, effective_to=None, is_deleted=False
    ).first()
    tenant = Tenant.query.get(g.tenant_id)

    content = _get_or_create_template(g.tenant_id, "salary_certificate")
    pronoun = "she" if emp.gender and emp.gender.value == "female" else "he"
    filled = content.replace("{{date}}", datetime.now().strftime("%d %B %Y"))
    filled = filled.replace("{{name}}", emp.full_name)
    filled = filled.replace("{{designation}}", emp.designation.name if emp.designation else "")
    filled = filled.replace("{{joining_date}}", emp.date_of_joining.strftime("%d %B %Y") if emp.date_of_joining else "")
    filled = filled.replace("{{gross_salary}}", f"{float(salary.ctc_monthly or 0):,.2f}" if salary else "N/A")
    filled = filled.replace("{{currency}}", tenant.currency if tenant else "INR")
    filled = filled.replace("{{pronoun}}", pronoun.capitalize())
    filled = filled.replace("{{hr_name}}", g.employee.full_name)
    filled = filled.replace("{{company_name}}", tenant.name if tenant else "")

    pdf_bytes = _generate_pdf(filled, "Salary Certificate")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"salary_certificate_{emp.employee_number}.pdf"
    )


@letters_bp.route("/appraisal/<emp_id>", methods=["POST"])
@require_auth(roles=["hr_admin"])
def appraisal_letter(emp_id):
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    data = request.get_json(silent=True) or {}
    content = _get_or_create_template(g.tenant_id, "appraisal")
    filled = content.replace("{{date}}", datetime.now().strftime("%d %B %Y"))
    filled = filled.replace("{{name}}", emp.full_name)
    filled = filled.replace("{{review_period}}", data.get("review_period", ""))
    filled = filled.replace("{{new_ctc}}", str(data.get("new_ctc", "")))
    filled = filled.replace("{{effective_date}}", data.get("effective_date", ""))
    filled = filled.replace("{{hr_name}}", g.employee.full_name)

    pdf_bytes = _generate_pdf(filled, "Appraisal Letter")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"appraisal_letter_{emp.employee_number}.pdf"
    )
