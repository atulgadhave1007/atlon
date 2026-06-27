import os
import uuid
from datetime import datetime, timezone, date
from flask import Blueprint, request, jsonify, g, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy import or_
from app.extensions import db
from app.models import (
    Employee, Department, Designation, Branch, EmployeeEducation,
    EmployeeExperience, EmployeeDocument, EmergencyContact,
    EmployeeBankDetail, EmployeeLifecycleEvent, EmployeeStatus, Role
)
from app.utils.auth import require_auth, log_action
from app.utils.security import sanitize_string, is_valid_email, validate_password

employees_bp = Blueprint("employees", __name__)


def _emp_summary(emp: Employee) -> dict:
    return {
        "id": str(emp.id),
        "employee_number": emp.employee_number,
        "name": emp.full_name,
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "work_email": emp.work_email,
        "personal_phone": emp.personal_phone,
        "work_phone": emp.work_phone,
        "status": emp.status.value,
        "role": emp.role.value,
        "employment_type": emp.employment_type.value if emp.employment_type else None,
        "department": emp.department.name if emp.department else None,
        "department_id": str(emp.department_id) if emp.department_id else None,
        "designation": emp.designation.name if emp.designation else None,
        "designation_id": str(emp.designation_id) if emp.designation_id else None,
        "branch": emp.branch.name if emp.branch else None,
        "date_of_joining": emp.date_of_joining.isoformat() if emp.date_of_joining else None,
        "photo_url": emp.photo_url,
        "is_active": emp.is_active,
        "reporting_manager_id": str(emp.reporting_manager_id) if emp.reporting_manager_id else None,
        "reporting_manager": emp.reporting_manager.full_name if emp.reporting_manager else None,
        # Frontend alias — some templates reference emp.email instead of emp.work_email
        "email": emp.work_email,
    }


# Display-case maps — PATCH handler lowercases incoming values before enum lookup, so these
# title-case return values round-trip safely through the frontend dropdowns.
_GENDER_DISPLAY = {
    "male": "Male", "female": "Female", "other": "Other",
    "prefer_not_to_say": "Prefer not to say",
}
_MARITAL_DISPLAY = {
    "single": "Single", "married": "Married",
    "divorced": "Divorced", "widowed": "Widowed",
}
_BANK_TYPE_DISPLAY = {"savings": "Savings", "current": "Current", "salary": "Salary"}


def _edu_dict(e) -> dict:
    """Add frontend alias keys to an EducationRecord dict."""
    d = e.to_dict()
    d["course"]         = d.get("degree", "")
    d["qualification"]  = d.get("degree", "")
    d["institute"]      = d.get("institution", "")
    d["specialization"] = d.get("field_of_study", "")
    d["passing_year"]   = d.get("year_to")
    return d


def _exp_dict(e) -> dict:
    """Add frontend alias keys to an EmployeeExperience dict and normalize Decimal ctc."""
    d = e.to_dict()
    d["last_designation"] = d.get("designation", "")
    d["location"]         = d.get("company_location", "")
    d["ctc"]              = float(d["ctc"]) if d.get("ctc") is not None else None
    return d


def _emp_detail(emp: Employee) -> dict:
    data = _emp_summary(emp)
    cf = emp.custom_fields or {}
    bank = emp.bank_details[0] if emp.bank_details else None
    edu = [_edu_dict(e) for e in emp.education]
    exp = [_exp_dict(e) for e in emp.experience]
    ec = [c.to_dict() for c in emp.emergency_contacts]

    _raw_bank_type = (bank.account_type or "").lower() if bank else ""

    data.update({
        "middle_name": emp.middle_name,
        "display_name": emp.display_name,
        # Return display-case values so frontend dropdown === comparisons match
        "gender": _GENDER_DISPLAY.get(emp.gender.value, emp.gender.value) if emp.gender else None,
        "date_of_birth": emp.date_of_birth.isoformat() if emp.date_of_birth else None,
        "blood_group": emp.blood_group.value if emp.blood_group else None,
        "marital_status": _MARITAL_DISPLAY.get(emp.marital_status.value, emp.marital_status.value) if emp.marital_status else None,
        "nationality": emp.nationality,
        "religion": emp.religion,
        "personal_email": emp.personal_email,
        "address_line1": emp.address_line1,
        "address_line2": emp.address_line2,
        "city": emp.city,
        "state": emp.state,
        "country": emp.country,
        "present_country": emp.country,
        "pincode": emp.pincode,
        "permanent_address": emp.permanent_address,
        "pan": emp.pan,
        "uan": emp.uan,
        "pf_number": emp.pf_number,
        "esi_number": emp.esi_number,
        # Frontend canonical aliases used in document tab displays
        "pan_number": emp.pan,
        "aadhaar_number": emp.aadhaar_last4,
        "uan_number": emp.uan,
        "esic_number": emp.esi_number,
        "passport_number": emp.passport_number,
        "passport_expiry": emp.passport_expiry.isoformat() if emp.passport_expiry else None,
        "emirates_id": emp.emirates_id,
        "date_of_confirmation": emp.date_of_confirmation.isoformat() if emp.date_of_confirmation else None,
        "probation_end_date": emp.probation_end_date.isoformat() if emp.probation_end_date else None,
        "date_of_exit": emp.date_of_exit.isoformat() if emp.date_of_exit else None,
        "bio": emp.bio,
        "linkedin_url": emp.linkedin_url,
        "skills": emp.skills,
        "languages": emp.languages,
        "mfa_enabled": emp.mfa_enabled,
        "custom_fields": cf,
        "t_shirt_size": cf.get("t_shirt_size"),
        "tshirt_size": cf.get("t_shirt_size"),   # alias — frontend dropdown reads this key
        "father_name": cf.get("father_name"),
        "caste_category": cf.get("caste_category"),
        "perm_address_line1": cf.get("perm_address_line1"),
        "perm_address_line2": cf.get("perm_address_line2"),
        "perm_city": cf.get("perm_city"),
        "perm_state": cf.get("perm_state"),
        "perm_pincode": cf.get("perm_pincode"),
        # Relationship data exposed with canonical names the frontend expects
        "education": edu,
        "education_records": edu,
        "experience": exp,
        "previous_employments": exp,
        "emergency_contacts": ec,
        "family_members": cf.get("family_members", []),
        # Bank — include frontend-named aliases alongside canonical keys
        "bank_name": bank.bank_name if bank else None,
        "bank_account_name": bank.account_holder_name if bank else None,
        "account_number_last4": bank.account_number_last4 if bank else None,
        "bank_account_number": bank.account_number_last4 if bank else None,  # pre-fill with masked last-4
        "ifsc_code": bank.ifsc_code if bank else None,
        "bank_branch": bank.branch_name if bank else None,
        "account_type": bank.account_type if bank else None,
        "bank_account_type": _BANK_TYPE_DISPLAY.get(_raw_bank_type, bank.account_type) if bank else None,
        "iban": bank.iban if bank else None,
        "swift_code": bank.swift_code if bank else None,
    })
    return data


@employees_bp.route("", methods=["GET"])
@require_auth(roles=["hr_admin", "payroll_admin", "manager"])
def list_employees():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 200)
    search = request.args.get("search", "")
    dept_id = request.args.get("department_id")
    desig_id = request.args.get("designation_id")
    status = request.args.get("status")
    employment_type = request.args.get("employment_type")

    q = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)

    if g.role == "manager":
        q = q.filter_by(reporting_manager_id=g.employee.id)

    if search:
        q = q.filter(or_(
            Employee.first_name.ilike(f"%{search}%"),
            Employee.last_name.ilike(f"%{search}%"),
            Employee.work_email.ilike(f"%{search}%"),
            Employee.employee_number.ilike(f"%{search}%"),
        ))
    if dept_id:
        q = q.filter_by(department_id=dept_id)
    if desig_id:
        q = q.filter_by(designation_id=desig_id)
    if status:
        q = q.filter_by(status=status)
    if employment_type:
        q = q.filter_by(employment_type=employment_type)

    pagination = q.order_by(Employee.first_name).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "employees": [_emp_summary(e) for e in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "page": page,
        "per_page": per_page,
    })


@employees_bp.route("", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_employee():
    from app.schemas.employee import EmployeeCreateSchema
    from app.schemas import validate_request
    data = request.get_json(silent=True) or {}
    validated, err = validate_request(EmployeeCreateSchema(), data)
    if err:
        return err

    email = validated["work_email"].strip().lower()

    if Employee.query.filter_by(tenant_id=g.tenant_id, work_email=email, is_deleted=False).first():
        return jsonify({"error": "An employee with this email already exists"}), 409

    emp_count = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).count()
    emp_number = validated.get("employee_number") or f"EMP{emp_count + 1:04d}"

    password = data.get("password") or f"Welcome@{datetime.now().year}"
    pw_errors = validate_password(password)
    if pw_errors:
        password = f"Welcome@{datetime.now().year}!"

    emp = Employee(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        employee_number=emp_number,
        first_name=sanitize_string(validated["first_name"], 100),
        middle_name=sanitize_string(validated.get("middle_name") or "", 100) or None,
        last_name=sanitize_string(validated["last_name"], 100),
        display_name=sanitize_string(validated.get("display_name") or "", 200) or None,
        work_email=email,
        personal_email=(validated.get("personal_email") or "").strip().lower() or None,
        personal_phone=sanitize_string(validated.get("personal_phone") or "", 20) or None,
        work_phone=sanitize_string(validated.get("work_phone") or "", 20) or None,
        date_of_joining=validated["date_of_joining"],
        department_id=validated.get("department_id"),
        designation_id=validated.get("designation_id"),
        branch_id=validated.get("branch_id"),
        reporting_manager_id=validated.get("reporting_manager_id"),
        employment_type=validated.get("employment_type", "full_time"),
        status=EmployeeStatus.PROBATION,
        role=Role(validated.get("role", "employee")),
        pan=sanitize_string(validated.get("pan") or "", 20) or None,
        uan=sanitize_string(validated.get("uan") or "", 20) or None,
        password_hash=Employee.hash_password(password),
        force_password_change=True,
        is_active=True,
    )
    if validated.get("date_of_birth"):
        emp.date_of_birth = validated["date_of_birth"]

    db.session.add(emp)

    _init_leave_balances(emp)

    db.session.commit()
    log_action("create_employee", "employee", emp.id)

    from app.services.email_service import queue_email
    from app.models import Tenant
    tenant = Tenant.query.get(g.tenant_id)
    queue_email(
        emp.work_email,
        f"Welcome to {tenant.name if tenant else 'the team'}!",
        'email/welcome.html',
        {
            'employee_name': emp.full_name,
            'employee_number': emp.employee_number,
            'temp_password': password,
            'date_of_joining': str(emp.date_of_joining),
            'company_name': tenant.name if tenant else '',
            'portal_url': f"https://{tenant.slug}.atlon.in" if tenant else '',
        },
    )

    return jsonify({
        "message": "Employee created successfully",
        "employee": _emp_summary(emp),
        "temp_password": password,
    }), 201


@employees_bp.route("/me", methods=["GET"])
@require_auth()
def get_me():
    emp = g.employee
    if not emp:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_emp_detail(emp))


@employees_bp.route("/me", methods=["PATCH"])
@require_auth()
def patch_me():
    emp = g.employee
    data = request.get_json(silent=True) or {}

    # ── Education records ────────────────────────────────────────────────────
    if "education_records" in data:
        EmployeeEducation.query.filter_by(
            tenant_id=g.tenant_id, employee_id=str(emp.id)
        ).delete()
        for rec in (data["education_records"] or []):
            # Frontend sends qualification+course, backend degree = course|qualification
            # Frontend sends passing_year for year_to; institute for institution
            degree_val = rec.get("course") or rec.get("qualification") or rec.get("degree") or ""
            institution_val = rec.get("institute") or rec.get("university") or rec.get("institution") or ""
            year_to_val = rec.get("passing_year") or rec.get("year_to")
            db.session.add(EmployeeEducation(
                id=uuid.uuid4(), tenant_id=g.tenant_id,
                employee_id=str(emp.id),
                degree=degree_val,
                field_of_study=rec.get("specialization") or rec.get("field_of_study") or "",
                institution=institution_val,
                year_from=int(rec["year_from"]) if rec.get("year_from") else None,
                year_to=int(year_to_val) if year_to_val else None,
                grade=rec.get("grade"),
            ))

    # ── Previous employments ─────────────────────────────────────────────────
    if "previous_employments" in data:
        EmployeeExperience.query.filter_by(
            tenant_id=g.tenant_id, employee_id=str(emp.id)
        ).delete()
        for rec in (data["previous_employments"] or []):
            raw_ctc = rec.get("ctc")
            from decimal import Decimal as _Decimal
            db.session.add(EmployeeExperience(
                id=uuid.uuid4(), tenant_id=g.tenant_id,
                employee_id=str(emp.id),
                company_name=rec.get("company") or rec.get("company_name") or "",
                designation=rec.get("last_designation") or rec.get("designation") or "",
                company_location=rec.get("company_location") or rec.get("location") or "",
                from_date=datetime.strptime(rec["from_date"], "%Y-%m-%d").date() if rec.get("from_date") else None,
                to_date=datetime.strptime(rec["to_date"], "%Y-%m-%d").date() if rec.get("to_date") else None,
                is_current=bool(rec.get("is_current")),
                reason_for_leaving=rec.get("reason_for_leaving") or rec.get("reason"),
                ctc=_Decimal(str(raw_ctc)) if raw_ctc not in (None, "", 0, "0") else None,
                manager_name=sanitize_string(rec.get("manager_name") or "", 200) or None,
                manager_email=sanitize_string(rec.get("manager_email") or "", 200) or None,
                manager_mobile=sanitize_string(rec.get("manager_mobile") or "", 20) or None,
            ))

    # ── Emergency contacts ───────────────────────────────────────────────────
    if "emergency_contacts" in data:
        EmergencyContact.query.filter_by(
            tenant_id=g.tenant_id, employee_id=str(emp.id)
        ).delete()
        for i, rec in enumerate(data["emergency_contacts"] or []):
            db.session.add(EmergencyContact(
                id=uuid.uuid4(), tenant_id=g.tenant_id,
                employee_id=str(emp.id),
                name=rec.get("name") or "",
                relation=rec.get("relation") or rec.get("relationship") or "Other",
                phone=rec.get("phone") or rec.get("mobile") or "",
                alt_phone=rec.get("alt_phone"),
                email=rec.get("email"),
                is_primary=(i == 0),
            ))

    # ── Family members (stored in custom_fields) ─────────────────────────────
    if "family_members" in data:
        cf = dict(emp.custom_fields or {})
        cf["family_members"] = data["family_members"]
        emp.custom_fields = cf

    # ── Bank details ─────────────────────────────────────────────────────────
    # Map frontend aliases to canonical bank keys
    if "bank_account_number" in data: data["account_number"] = data["bank_account_number"]
    if "bank_account_type" in data: data["account_type"] = data["bank_account_type"].lower() if data.get("bank_account_type") else None
    if "bank_account_name" in data: data["account_holder_name"] = data["bank_account_name"]
    if "bank_branch" in data: data["branch_name"] = data["bank_branch"]
    bank_keys = {"bank_name", "account_holder_name", "account_number", "ifsc_code",
                 "branch_name", "account_type", "iban", "swift_code", "routing_number"}
    if bank_keys & set(data.keys()):
        bank = EmployeeBankDetail.query.filter_by(
            tenant_id=g.tenant_id, employee_id=str(emp.id), is_deleted=False
        ).first()
        acc_num = data.get("account_number", "")
        if not bank:
            bank = EmployeeBankDetail(
                id=uuid.uuid4(), tenant_id=g.tenant_id,
                employee_id=str(emp.id),
                bank_name=data.get("bank_name") or "",
                account_holder_name=data.get("account_holder_name"),
                account_number_encrypted=acc_num,
                account_number_last4=acc_num[-4:] if len(acc_num) >= 4 else acc_num,
                ifsc_code=data.get("ifsc_code"),
                branch_name=data.get("branch_name"),
                iban=data.get("iban"),
                swift_code=data.get("swift_code"),
                routing_number=data.get("routing_number"),
                account_type=data.get("account_type", "savings"),
                is_primary=True,
            )
            db.session.add(bank)
        else:
            if data.get("bank_name"): bank.bank_name = data["bank_name"]
            if data.get("account_holder_name") is not None: bank.account_holder_name = data["account_holder_name"]
            if acc_num:
                bank.account_number_encrypted = acc_num
                bank.account_number_last4 = acc_num[-4:] if len(acc_num) >= 4 else acc_num
            if data.get("ifsc_code"): bank.ifsc_code = data["ifsc_code"]
            if data.get("branch_name") is not None: bank.branch_name = data["branch_name"]
            if data.get("account_type"): bank.account_type = data["account_type"]
            if data.get("iban"): bank.iban = data["iban"]
            if data.get("swift_code"): bank.swift_code = data["swift_code"]

    # ── Custom fields (t_shirt_size, father_name, caste_category, perm_address) ─
    # Map tshirt_size (frontend) → t_shirt_size (canonical)
    if "tshirt_size" in data: data["t_shirt_size"] = data["tshirt_size"]
    custom_keys = {
        "t_shirt_size", "father_name", "caste_category",
        "perm_address_line1", "perm_address_line2", "perm_city", "perm_state", "perm_pincode",
        "perm_country", "perm_same_as_present",
    }
    cf_updates = {k: data[k] for k in custom_keys if k in data}
    if cf_updates:
        cf = dict(emp.custom_fields or {})
        cf.update(cf_updates)
        emp.custom_fields = cf

    # Map frontend field name aliases → canonical DB column names
    _FIELD_ALIAS = {
        "present_address_line1": "address_line1",
        "present_address_line2": "address_line2",
        "present_city": "city",
        "present_state": "state",
        "present_pincode": "pincode",
        "present_country": "country",
        "pan_number": "pan",
        "uan_number": "uan",
        "esic_number": "esi_number",
    }
    for alias, canonical in _FIELD_ALIAS.items():
        if alias in data and data[alias] is not None:
            data[canonical] = data[alias]

    # ── Direct Employee fields ────────────────────────────────────────────────
    str_fields = [
        "first_name", "last_name", "middle_name", "display_name",
        "personal_email", "personal_phone", "work_phone",
        "nationality", "religion", "bio", "linkedin_url",
        "address_line1", "address_line2", "city", "state", "country", "pincode",
        "pan", "uan", "pf_number", "esi_number", "aadhaar_last4",
        "passport_number", "driving_license", "visa_number", "emirates_id",
        "permanent_address",
    ]
    for f in str_fields:
        if f in data and data[f] is not None:
            setattr(emp, f, sanitize_string(str(data[f]), 200) if data[f] else None)

    # Enum fields — normalise to lowercase/canonical before parsing
    from app.models.employee import Gender, BloodGroup, MaritalStatus
    _GENDER_MAP = {"male": "male", "female": "female", "other": "other", "prefer not to say": "prefer_not_to_say", "prefer_not_to_say": "prefer_not_to_say"}
    _MARITAL_MAP = {"single": "single", "married": "married", "divorced": "divorced", "widowed": "widowed"}
    if "gender" in data and data["gender"]:
        try: emp.gender = Gender(_GENDER_MAP.get(str(data["gender"]).lower(), str(data["gender"]).lower()))
        except ValueError: pass
    if "blood_group" in data and data["blood_group"]:
        try: emp.blood_group = BloodGroup(data["blood_group"])
        except ValueError: pass
    if "marital_status" in data and data["marital_status"]:
        try: emp.marital_status = MaritalStatus(_MARITAL_MAP.get(str(data["marital_status"]).lower(), str(data["marital_status"]).lower()))
        except ValueError: pass

    # Date fields
    for date_field in ["date_of_birth", "passport_expiry", "visa_expiry"]:
        if data.get(date_field):
            try:
                setattr(emp, date_field, datetime.strptime(data[date_field], "%Y-%m-%d").date())
            except (ValueError, TypeError):
                pass

    # JSON list fields
    for json_field in ["skills", "languages"]:
        if json_field in data:
            val = data[json_field]
            if isinstance(val, str):
                val = [s.strip() for s in val.split(",") if s.strip()]
            setattr(emp, json_field, val)

    db.session.commit()
    log_action("update_profile", "employee", emp.id)
    return jsonify(_emp_detail(emp))


_PHOTO_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'uploads', 'photos')
_ALLOWED_PHOTO_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


@employees_bp.route("/me/photo", methods=["POST"])
@require_auth()
def upload_my_photo():
    if 'photo' not in request.files:
        return jsonify({"error": "No photo file provided"}), 400
    file = request.files['photo']
    if not file or file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in _ALLOWED_PHOTO_EXTS:
        return jsonify({"error": f"Invalid file type. Allowed: {', '.join(_ALLOWED_PHOTO_EXTS)}"}), 400
    filename = secure_filename(f"{g.tenant_id}_{g.employee.id}.{ext}")
    os.makedirs(_PHOTO_UPLOAD_DIR, exist_ok=True)
    file.save(os.path.join(_PHOTO_UPLOAD_DIR, filename))
    photo_url = f"/api/uploads/photos/{filename}"
    emp = g.employee
    emp.photo_url = photo_url
    db.session.commit()
    log_action("upload_photo", "employee", emp.id)
    return jsonify({"message": "Photo updated", "photo_url": photo_url})


@employees_bp.route("/uploads/photos/<filename>", methods=["GET"])
def serve_photo(filename):
    safe = secure_filename(filename)
    return send_from_directory(_PHOTO_UPLOAD_DIR, safe)


@employees_bp.route("/me/photo", methods=["DELETE"])
@require_auth()
def delete_my_photo():
    emp = g.employee
    emp.photo_url = None
    db.session.commit()
    return jsonify({"message": "Photo removed"})


@employees_bp.route("/me/documents", methods=["POST"])
@require_auth()
def upload_my_document():
    from app.services.storage_service import upload_file, allowed_file
    emp = g.employee
    category = sanitize_string(request.form.get("category", "general"), 50)
    doc_name = sanitize_string(request.form.get("doc_name", category), 200)
    file = request.files.get("doc_file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400
    if not allowed_file(file.content_type):
        return jsonify({"error": "File type not allowed"}), 415
    try:
        path = f"employees/{emp.employee_number}/{category}/{file.filename}"
        file_url = upload_file(file, path, file.content_type)
    except ValueError as e:
        return jsonify({"error": str(e)}), 415
    except Exception as e:
        return jsonify({"error": "Upload failed, please try again"}), 500
    doc = EmployeeDocument(
        id=uuid.uuid4(), tenant_id=g.tenant_id,
        employee_id=str(emp.id),
        document_type=category,
        document_name=doc_name,
        file_url=file_url,
        mime_type=file.content_type,
    )
    db.session.add(doc)
    db.session.commit()
    return jsonify({"id": str(doc.id), "file_url": file_url}), 201


@employees_bp.route("/profile-requests", methods=["GET"])
@require_auth()
def get_profile_requests():
    from app.models.notification import AuditLog
    status_filter = request.args.get("status", "")
    q = AuditLog.query.filter(
        AuditLog.action == "profile_change_request",
        AuditLog.entity_type == "employee",
        AuditLog.entity_id == str(g.employee.id),
    )
    if status_filter:
        pass  # AuditLog doesn't have a status field; return all
    logs = q.order_by(AuditLog.created_at.desc()).limit(50).all()
    requests_list = []
    for log in logs:
        changes = log.changes or {}
        requests_list.append({
            "id": str(log.id),
            "section": changes.get("section", "-"),
            "employee_id": g.employee.employee_number,
            "employee_name": g.employee.full_name,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "remark": changes.get("remark", ""),
            "status": changes.get("status", "pending"),
        })
    return jsonify({"requests": requests_list})


@employees_bp.route("/profile-requests", methods=["POST"])
@require_auth()
def submit_profile_request():
    from app.models.notification import AuditLog
    data = request.get_json(silent=True) or {}
    section = data.get("section", "")
    if not section:
        return jsonify({"error": "section is required"}), 400
    log = AuditLog(
        actor_id=str(g.employee.id),
        action="profile_change_request",
        entity_type="employee",
        entity_id=str(g.employee.id),
        changes={
            "section": section,
            "field": data.get("field", ""),
            "old_value": data.get("old_value", ""),
            "new_value": data.get("new_value", ""),
            "remark": data.get("remark", ""),
            "status": "pending",
        },
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"message": "Profile request submitted", "id": str(log.id)}), 201


@employees_bp.route("/lifecycle-events", methods=["GET"])
@require_auth(roles=["hr_admin", "manager"])
def all_lifecycle_events():
    """List all lifecycle events for the tenant (admin/manager view)."""
    from app.models import EmployeeLifecycleEvent
    event_type = request.args.get("event_type")
    q = EmployeeLifecycleEvent.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    )
    if g.role == "manager":
        team_ids = [str(e.id) for e in Employee.query.filter_by(
            tenant_id=g.tenant_id, reporting_manager_id=g.employee.id, is_deleted=False
        ).all()]
        q = q.filter(EmployeeLifecycleEvent.employee_id.in_(team_ids))
    if event_type:
        q = q.filter_by(event_type=event_type)
    events = q.order_by(EmployeeLifecycleEvent.effective_date.desc()).limit(100).all()
    result = []
    for ev in events:
        emp = Employee.query.get(ev.employee_id)
        d = ev.to_dict()
        d["employee_name"] = emp.full_name if emp else "-"
        d["employee_number"] = emp.employee_number if emp else "-"
        result.append(d)
    return jsonify({"events": result})


@employees_bp.route("/<emp_id>", methods=["GET"])
@require_auth()
def get_employee(emp_id):
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    if g.role == "employee" and str(g.employee.id) != emp_id:
        return jsonify({"error": "Access denied"}), 403
    return jsonify(_emp_detail(emp))


@employees_bp.route("/<emp_id>", methods=["PUT"])
@require_auth()
def update_employee(emp_id):
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()

    is_self = g.employee and str(g.employee.id) == emp_id
    is_hr = g.role == "hr_admin"

    if not is_hr and not is_self:
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}

    # Employees can only update their own contact/personal fields
    employee_editable = [
        "personal_email", "personal_phone", "address_line1", "address_line2",
        "city", "state", "pincode", "permanent_address", "blood_group",
        "marital_status", "bio", "linkedin_url", "skills", "languages",
    ]
    hr_fields = [
        "first_name", "last_name", "middle_name", "display_name", "work_email",
        "work_phone", "date_of_joining", "date_of_birth", "gender", "nationality",
        "department_id", "designation_id", "branch_id", "reporting_manager_id",
        "employment_type", "role", "status", "date_of_confirmation",
        "probation_end_date", "pan", "uan", "pf_number", "esi_number",
        "passport_number", "passport_expiry", "emirates_id", "photo_url",
    ]

    fields_to_update = employee_editable if not is_hr else employee_editable + hr_fields

    _DATE_FIELDS = {"date_of_joining", "date_of_birth", "date_of_confirmation", "probation_end_date", "passport_expiry"}
    _ENUM_FIELDS_HR = {
        "gender": ("app.models.employee", "Gender"),
        "blood_group": ("app.models.employee", "BloodGroup"),
        "marital_status": ("app.models.employee", "MaritalStatus"),
        "employment_type": ("app.models.employee", "EmploymentType"),
        "status": ("app.models.employee", "EmployeeStatus"),
        "role": ("app.models.employee", "Role"),
    }

    old_values = {}
    new_values = {}
    for field in fields_to_update:
        if field not in data:
            continue
        old_values[field] = getattr(emp, field, None)
        val = data[field]
        if field in _DATE_FIELDS:
            if val:
                try:
                    val = datetime.strptime(str(val), "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
            else:
                val = None
        elif field in _ENUM_FIELDS_HR:
            if val:
                mod_path, cls_name = _ENUM_FIELDS_HR[field]
                import importlib
                mod = importlib.import_module(mod_path)
                enum_cls = getattr(mod, cls_name)
                try:
                    val = enum_cls(str(val).lower())
                except ValueError:
                    continue
        elif isinstance(val, str):
            val = sanitize_string(val)
        setattr(emp, field, val)
        new_values[field] = val

    db.session.commit()
    log_action("update_employee", "employee", emp.id, old_values=old_values, new_values=new_values)
    return jsonify({"message": "Employee updated", "employee": _emp_detail(emp)})


@employees_bp.route("/<emp_id>", methods=["DELETE"])
@require_auth(roles=["hr_admin"])
def delete_employee(emp_id):
    emp = Employee.query.filter_by(
        id=emp_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    emp.soft_delete()
    emp.is_active = False
    db.session.commit()
    log_action("delete_employee", "employee", emp.id)
    return jsonify({"message": "Employee removed"})


@employees_bp.route("/bulk-import", methods=["POST"])
@require_auth(roles=["hr_admin"])
def bulk_import():
    data = request.get_json(silent=True) or {}
    rows = data.get("employees", [])
    if not rows:
        return jsonify({"error": "No employees provided"}), 400
    if len(rows) > 1000:
        return jsonify({"error": "Maximum 1000 employees per import"}), 400

    created = 0
    errors = []
    emp_count = Employee.query.filter_by(tenant_id=g.tenant_id, is_deleted=False).count()

    for i, row in enumerate(rows):
        try:
            email = (row.get("work_email") or "").strip().lower()
            if not email or not is_valid_email(email):
                errors.append({"row": i + 1, "error": f"Invalid email: {email}"})
                continue
            if Employee.query.filter_by(tenant_id=g.tenant_id, work_email=email, is_deleted=False).first():
                errors.append({"row": i + 1, "error": f"Email already exists: {email}"})
                continue

            emp_count += 1
            emp = Employee(
                id=uuid.uuid4(),
                tenant_id=g.tenant_id,
                employee_number=row.get("employee_number") or f"EMP{emp_count:04d}",
                first_name=sanitize_string(row.get("first_name", ""), 100),
                last_name=sanitize_string(row.get("last_name", ""), 100),
                work_email=email,
                personal_phone=sanitize_string(row.get("phone", ""), 20) or None,
                date_of_joining=datetime.strptime(row["date_of_joining"], "%Y-%m-%d").date() if row.get("date_of_joining") else datetime.now().date(),
                status=EmployeeStatus.PROBATION,
                role=Role.EMPLOYEE,
                password_hash=Employee.hash_password(f"Welcome@{datetime.now().year}!"),
                force_password_change=True,
                is_active=True,
            )
            db.session.add(emp)
            _init_leave_balances(emp)
            created += 1
        except Exception as e:
            errors.append({"row": i + 1, "error": str(e)})

    db.session.commit()
    log_action("bulk_import_employees", "employee", result="success" if not errors else "partial")
    return jsonify({"created": created, "errors": errors})


def _build_org_tree(nodes: list) -> dict:
    """Convert flat node list (with parent_id) into nested tree the frontend renders."""
    node_map = {n["id"]: {**n, "children": []} for n in nodes}
    roots = []
    for node in node_map.values():
        pid = node.get("parent_id")
        if pid and pid in node_map:
            node_map[pid]["children"].append(node)
        else:
            roots.append(node)
    if not roots:
        return {"name": "Organization", "designation": "", "children": list(node_map.values())}
    if len(roots) == 1:
        return roots[0]
    return {"name": "Organization", "designation": "", "department": "", "photo_url": None, "children": roots}


@employees_bp.route("/org-chart", methods=["GET"])
@require_auth()
def org_chart():
    employees = Employee.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False, is_active=True
    ).all()
    nodes = [
        {
            "id": str(e.id),
            "name": e.full_name,
            "designation": e.designation.name if e.designation else None,
            "department": e.department.name if e.department else None,
            "photo_url": e.photo_url,
            "parent_id": str(e.reporting_manager_id) if e.reporting_manager_id else None,
        }
        for e in employees
    ]
    return jsonify({"tree": _build_org_tree(nodes), "nodes": nodes})


def _init_leave_balances(emp: Employee):
    """Set up default leave balances for new employee."""
    from app.models import LeaveType, LeaveBalance
    import uuid as _uuid
    year = datetime.now().year
    types = LeaveType.query.filter_by(tenant_id=str(emp.tenant_id), is_deleted=False).all()
    for lt in types:
        bal = LeaveBalance(
            id=_uuid.uuid4(),
            tenant_id=str(emp.tenant_id),
            employee_id=emp.id,
            leave_type_id=lt.id,
            year=year,
            opening_balance=0,
            credited=0,
        )
        db.session.add(bal)
