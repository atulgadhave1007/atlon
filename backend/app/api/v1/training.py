import uuid
from flask import Blueprint, request, jsonify, g
from app.extensions import db
from app.models import Course, CourseEnrollment, ModuleProgress, Survey, SurveyResponse, EnrollmentStatus
from app.utils.auth import require_auth

training_bp = Blueprint("training", __name__)


@training_bp.route("/courses", methods=["GET"])
@require_auth()
def list_courses():
    q = Course.query.filter_by(tenant_id=g.tenant_id, is_deleted=False, is_active=True)
    courses = q.order_by(Course.title).all()
    return jsonify({"courses": [c.to_dict() for c in courses]})


@training_bp.route("/courses", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_course():
    data = request.get_json(silent=True) or {}
    course = Course(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        title=data.get("title", "").strip(),
        code=data.get("code", "").strip().upper(),
        description=data.get("description"),
        category=data.get("category"),
        type=data.get("type", "video"),
        duration_minutes=int(data.get("duration_minutes", 0)),
        is_mandatory=bool(data.get("is_mandatory", False)),
        is_self_enroll=bool(data.get("is_self_enroll", True)),
        passing_score=int(data.get("passing_score", 70)),
        skills_covered=data.get("skills_covered", []),
        applicable_departments=data.get("applicable_departments", []),
        created_by_id=str(g.employee.id),
    )
    db.session.add(course)
    db.session.commit()
    return jsonify({"course": course.to_dict()}), 201


@training_bp.route("/courses/<course_id>/enroll", methods=["POST"])
@require_auth()
def enroll(course_id):
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id") or str(g.employee.id)
    if g.role == "employee":
        employee_id = str(g.employee.id)

    existing = CourseEnrollment.query.filter_by(
        tenant_id=g.tenant_id, course_id=course_id, employee_id=employee_id, is_deleted=False
    ).first()
    if existing:
        return jsonify({"error": "Already enrolled"}), 409

    enrollment = CourseEnrollment(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        course_id=course_id,
        employee_id=employee_id,
        status=EnrollmentStatus.ENROLLED,
        enrolled_by_id=str(g.employee.id),
    )
    db.session.add(enrollment)
    db.session.commit()
    return jsonify({"enrollment": enrollment.to_dict()}), 201


@training_bp.route("/my-courses", methods=["GET"])
@require_auth()
def my_courses():
    enrollments = CourseEnrollment.query.filter_by(
        tenant_id=g.tenant_id, employee_id=str(g.employee.id), is_deleted=False
    ).all()
    result = []
    for e in enrollments:
        d = e.to_dict()
        d["course_title"] = e.course.title if e.course else None
        result.append(d)
    return jsonify({"enrollments": result})


@training_bp.route("/enrollments/<enr_id>/progress", methods=["POST"])
@require_auth()
def update_progress(enr_id):
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    enr = CourseEnrollment.query.filter_by(
        id=enr_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    enr.progress_pct = float(data.get("progress_pct", 0))
    if enr.progress_pct >= 100:
        enr.status = EnrollmentStatus.COMPLETED
        enr.completed_at = datetime.now(timezone.utc)
        score = float(data.get("score", 0))
        enr.score = score
        if score < (enr.course.passing_score or 70):
            enr.status = EnrollmentStatus.FAILED
    else:
        enr.status = EnrollmentStatus.IN_PROGRESS
    db.session.commit()
    return jsonify({"enrollment": enr.to_dict()})


@training_bp.route("/surveys", methods=["GET"])
@require_auth()
def list_surveys():
    q = Survey.query.filter_by(tenant_id=g.tenant_id, is_deleted=False, status="active")
    return jsonify({"surveys": [s.to_dict() for s in q.all()]})


@training_bp.route("/surveys", methods=["POST"])
@require_auth(roles=["hr_admin"])
def create_survey():
    data = request.get_json(silent=True) or {}
    survey = Survey(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        title=data.get("title", "").strip(),
        description=data.get("description"),
        survey_type=data.get("survey_type", "general"),
        is_anonymous=bool(data.get("is_anonymous", True)),
        questions=data.get("questions", []),
        target_all=bool(data.get("target_all", True)),
        target_departments=data.get("target_departments", []),
        created_by_id=str(g.employee.id),
        status="draft",
    )
    db.session.add(survey)
    db.session.commit()
    return jsonify({"survey": survey.to_dict()}), 201


@training_bp.route("/surveys/<survey_id>/respond", methods=["POST"])
@require_auth()
def respond_survey(survey_id):
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    survey = Survey.query.filter_by(
        id=survey_id, tenant_id=g.tenant_id, is_deleted=False
    ).first_or_404()
    response = SurveyResponse(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        survey_id=survey_id,
        employee_id=None if survey.is_anonymous else str(g.employee.id),
        answers=data.get("answers", {}),
        is_anonymous=survey.is_anonymous,
    )
    db.session.add(response)
    survey.response_count = (survey.response_count or 0) + 1
    db.session.commit()
    return jsonify({"message": "Response recorded"})
