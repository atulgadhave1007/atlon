import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import JobPosting, JobApplication, Interview, OfferLetter, JobStatus, ApplicationStatus
from app.utils.auth import require_auth
from app.utils.tenant_refs import reject_foreign_refs
from app.utils.security import sanitize_string

recruitment_bp = Blueprint("recruitment", __name__)


@recruitment_bp.route("/jobs", methods=["GET"])
@require_auth()
def list_jobs():
    status = request.args.get("status")
    q = JobPosting.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)
    if status:
        q = q.filter_by(status=status)
    jobs = q.order_by(JobPosting.created_at.desc()).all()
    return jsonify({"jobs": [j.to_dict() for j in jobs]})


@recruitment_bp.route("/jobs", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_job():
    data = request.get_json(silent=True) or {}
    import secrets, string
    code = "JOB" + "".join(secrets.choice(string.digits) for _ in range(5))
    _ref_err = reject_foreign_refs(data, {"department_id": "Department", "designation_id": "Designation", "branch_id": "Branch", "hiring_manager_id": "Employee"})
    if _ref_err:
        return _ref_err
    job = JobPosting(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        title=sanitize_string(data.get("title", ""), 200),
        job_code=code,
        department_id=data.get("department_id"),
        designation_id=data.get("designation_id"),
        branch_id=data.get("branch_id"),
        hiring_manager_id=data.get("hiring_manager_id"),
        recruiter_id=str(g.employee.id),
        description=sanitize_string(data.get("description", ""), 5000),
        requirements=sanitize_string(data.get("requirements", ""), 5000),
        responsibilities=sanitize_string(data.get("responsibilities", ""), 5000),
        employment_type=data.get("employment_type", "full_time"),
        experience_min=int(data.get("experience_min", 0)),
        experience_max=data.get("experience_max"),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        is_salary_visible=bool(data.get("is_salary_visible", False)),
        openings=int(data.get("openings", 1)),
        status=JobStatus.DRAFT,
        is_internal=bool(data.get("is_internal", False)),
        is_remote=bool(data.get("is_remote", False)),
        skills_required=data.get("skills_required", []),
    )
    db.session.add(job)
    db.session.commit()
    return jsonify({"job": job.to_dict()}), 201


@recruitment_bp.route("/jobs/<job_id>/publish", methods=["POST"])
@require_auth(roles=["hr_admin"])
def publish_job(job_id):
    job = JobPosting.query.filter_by(id=job_id, tenant_id=g.tenant_id, is_deleted=False).first_or_404()
    job.status = JobStatus.OPEN
    job.published_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "Job published", "job": job.to_dict()})


@recruitment_bp.route("/jobs/<job_id>/applications", methods=["GET"])
@require_auth(roles=["hr_admin"])
def list_applications(job_id):
    apps = JobApplication.query.filter_by(
        tenant_id=g.tenant_id, job_posting_id=job_id, is_deleted=False
    ).order_by(JobApplication.applied_at.desc()).all()
    return jsonify({"applications": [a.to_dict() for a in apps]})


@recruitment_bp.route("/jobs/<job_id>/apply", methods=["POST"])
def apply_for_job(job_id):
    job = JobPosting.query.filter_by(id=job_id, is_deleted=False, status=JobStatus.OPEN).first_or_404()
    data = request.get_json(silent=True) or {}
    app = JobApplication(
        id=uuid.uuid4(),
        tenant_id=str(job.tenant_id),
        job_posting_id=job_id,
        candidate_name=sanitize_string(data.get("name", ""), 200),
        candidate_email=data.get("email", "").strip().lower(),
        candidate_phone=data.get("phone", ""),
        current_company=sanitize_string(data.get("current_company", ""), 200),
        current_designation=sanitize_string(data.get("current_designation", ""), 200),
        current_ctc=data.get("current_ctc"),
        expected_ctc=data.get("expected_ctc"),
        notice_period_days=data.get("notice_period_days"),
        total_experience_years=data.get("total_experience_years"),
        resume_url=data.get("resume_url", ""),
        cover_letter=sanitize_string(data.get("cover_letter", ""), 2000),
        source=data.get("source", "direct"),
        status=ApplicationStatus.APPLIED,
    )
    db.session.add(app)
    db.session.commit()
    return jsonify({"message": "Application submitted", "id": str(app.id)}), 201


@recruitment_bp.route("/applications/<app_id>/move", methods=["POST"])
@require_auth(roles=["hr_admin"])
def move_application(app_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    app = JobApplication.query.filter_by(
        id=app_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    old_status = app.status
    app.status = new_status
    history = list(app.stage_history or [])
    history.append({
        "from": old_status.value if hasattr(old_status, "value") else old_status,
        "to": new_status,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "changed_by": str(g.employee.id),
        "remarks": data.get("remarks", ""),
    })
    app.stage_history = history
    if new_status in ("rejected", "withdrawn"):
        app.rejection_reason = data.get("reason")
    db.session.commit()
    return jsonify({"application": app.to_dict()})


@recruitment_bp.route("/applications/<app_id>/interviews", methods=["POST"])
@require_auth(roles=["hr_admin"])
def schedule_interview(app_id):
    data = request.get_json(silent=True) or {}
    interview = Interview(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        application_id=app_id,
        round_number=int(data.get("round_number", 1)),
        round_name=data.get("round_name", ""),
        interview_type=data.get("type", "video"),
        scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
        duration_minutes=int(data.get("duration_minutes", 60)),
        meeting_link=data.get("meeting_link"),
        interviewers=data.get("interviewers", []),
        status="scheduled",
    )
    db.session.add(interview)
    db.session.commit()
    return jsonify({"interview": interview.to_dict()}), 201
