"""Tests for the open-source security hardening:
super admin bootstrap, production config checks, super-admin token checks,
and tenant-ownership checks on IDs sent in request bodies.
"""
import pathlib
import uuid
from datetime import date

import pytest
from sqlalchemy.pool import StaticPool

from app import create_app, _bootstrap_super_admin
from app.config import TestingConfig, ProductionConfig, validate_production_config
from app.extensions import db as _db

STRONG_SECRET_A = "a" * 20 + "-Strong-Secret-Key-For-Tests-0001"
STRONG_SECRET_B = "b" * 20 + "-Strong-Jwt-Secret-For-Tests-0002"


def _isolated_config(base, **attrs):
    """A config class with its own in-memory DB, so bootstrap starts from empty."""
    defaults = dict(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"check_same_thread": False},
                                   "poolclass": StaticPool},
        RATELIMIT_ENABLED=False,
        RATELIMIT_STORAGE_URI="memory://",
        SECRET_KEY=STRONG_SECRET_A,
        JWT_SECRET=STRONG_SECRET_B,
        CORS_ORIGINS=["https://hr.example.com"],
        SUPER_ADMIN_EMAIL="",
        SUPER_ADMIN_PASSWORD="",
    )
    defaults.update(attrs)
    return type("IsolatedConfig", (base,), defaults)


class _DevLikeConfig(TestingConfig):
    """Development behaviour (not TESTING, not production) on an in-memory DB."""
    TESTING = False


def _super_admins(app):
    from app.models import SuperAdmin
    with app.app_context():
        return [(s.email, s.password_hash) for s in SuperAdmin.query.all()]


# ── Super admin bootstrap ───────────────────────────────────────────────────

class TestSuperAdminBootstrap:
    def test_no_hardcoded_default_password_in_app_code(self):
        app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
        for path in app_dir.rglob("*.py"):
            assert "AtlonAdmin@123" not in path.read_text(encoding="utf-8"), path

    def test_env_credentials_create_admin_who_can_log_in(self):
        app = create_app(_isolated_config(
            _DevLikeConfig, SUPER_ADMIN_EMAIL="Owner@Example.com",
            SUPER_ADMIN_PASSWORD="Str0ng!Passw0rd"))
        admins = _super_admins(app)
        assert [a[0] for a in admins] == ["owner@example.com"]
        assert "Str0ng!Passw0rd" not in admins[0][1]  # stored hashed

        with app.app_context():
            resp = app.test_client().post("/api/auth/login", json={
                "username": "owner@example.com", "password": "Str0ng!Passw0rd"})
        assert resp.status_code == 200
        assert resp.get_json()["user"]["role"] == "super_admin"

    def test_production_without_password_creates_nothing(self, caplog):
        app = create_app(_isolated_config(
            ProductionConfig, SUPER_ADMIN_EMAIL="owner@example.com"))
        assert _super_admins(app) == []
        assert "SUPER_ADMIN_PASSWORD is not set" in caplog.text

    def test_missing_email_creates_nothing(self, caplog):
        app = create_app(_isolated_config(
            _DevLikeConfig, SUPER_ADMIN_PASSWORD="Str0ng!Passw0rd"))
        assert _super_admins(app) == []
        assert "SUPER_ADMIN_EMAIL is not set" in caplog.text

    def test_weak_env_password_is_rejected_and_not_logged(self, caplog):
        app = create_app(_isolated_config(
            _DevLikeConfig, SUPER_ADMIN_EMAIL="owner@example.com",
            SUPER_ADMIN_PASSWORD="weak"))
        assert _super_admins(app) == []
        assert "does not meet the password policy" in caplog.text
        assert "weak" not in caplog.text.replace("weak)", "").split("policy")[0]

    def test_development_generates_password_printed_exactly_once(self, capsys):
        app = create_app(_isolated_config(
            _DevLikeConfig, SUPER_ADMIN_EMAIL="owner@example.com"))
        first = capsys.readouterr().out
        assert "Super admin created: owner@example.com" in first
        assert "Generated password" in first
        assert len(_super_admins(app)) == 1

        # Restarting (bootstrap again) must not create or print anything.
        with app.app_context():
            assert _bootstrap_super_admin(app) is None
        assert "Generated password" not in capsys.readouterr().out
        assert len(_super_admins(app)) == 1


# ── Production config validation ────────────────────────────────────────────

class TestProductionConfig:
    def test_defaults_are_rejected(self):
        problems = validate_production_config({
            "SECRET_KEY": "change-me-in-production-64-chars-min",
            "JWT_SECRET": "change-me-jwt-secret-64-chars-min",
            "CORS_ORIGINS": ["*"],
        })
        assert len(problems) == 3

    def test_short_or_identical_secrets_are_rejected(self):
        assert validate_production_config({
            "SECRET_KEY": "short", "JWT_SECRET": STRONG_SECRET_B,
            "CORS_ORIGINS": ["https://hr.example.com"]})
        assert validate_production_config({
            "SECRET_KEY": STRONG_SECRET_A, "JWT_SECRET": STRONG_SECRET_A,
            "CORS_ORIGINS": ["https://hr.example.com"]})

    def test_empty_cors_is_rejected(self):
        assert validate_production_config({
            "SECRET_KEY": STRONG_SECRET_A, "JWT_SECRET": STRONG_SECRET_B,
            "CORS_ORIGINS": []})

    def test_good_config_passes(self):
        assert validate_production_config({
            "SECRET_KEY": STRONG_SECRET_A, "JWT_SECRET": STRONG_SECRET_B,
            "CORS_ORIGINS": ["https://hr.example.com"]}) == []

    def test_create_app_refuses_weak_production_config(self):
        with pytest.raises(RuntimeError, match="Refusing to start in production"):
            create_app(_isolated_config(ProductionConfig, SECRET_KEY="dev"))

    def test_create_app_refuses_wildcard_cors_in_production(self):
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            create_app(_isolated_config(ProductionConfig, CORS_ORIGINS=["*"]))


# ── Super-admin tokens ──────────────────────────────────────────────────────

def test_super_token_for_unknown_admin_is_rejected(app, client, seeded):
    from app.utils.auth import generate_access_token
    token = generate_access_token(str(uuid.uuid4()), "super_admin", is_super=True)
    resp = client.get("/api/employees",
                      headers={"Authorization": f"Bearer {token}", "X-Tenant-Slug": "testco"})
    assert resp.status_code == 401


# ── Tenant isolation ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def other_tenant(app, db, seeded):
    """A second tenant with its own department, employee and ticket category."""
    from app.models import (Tenant, Department, Employee, TicketCategory,
                            TenantStatus, CountryCode)
    from app.utils.security import hash_password

    tenant = Tenant.query.filter_by(slug="othercorp").first()
    if not tenant:
        tenant = Tenant(name="Other Corp", slug="othercorp", email="admin@other.test",
                        country=CountryCode.IN, status=TenantStatus.ACTIVE,
                        plan_id=str(seeded["tenant"].plan_id))
        db.session.add(tenant)
        db.session.flush()
    dept = Department(tenant_id=str(tenant.id), name="Other Dept")
    emp = Employee(
        tenant_id=str(tenant.id), employee_number="OTH001", first_name="Olga",
        last_name="Other", work_email=f"olga-{uuid.uuid4().hex[:6]}@other.test",
        password_hash=hash_password("Other@1234"), role="hr_admin", status="active",
        employment_type="full_time", date_of_joining=date(2023, 1, 1),
        force_password_change=False)
    cat = TicketCategory(tenant_id=str(tenant.id), name="Other IT")
    db.session.add_all([dept, emp, cat])
    db.session.commit()
    return {"tenant": tenant, "dept_id": str(dept.id), "emp_id": str(emp.id),
            "category_id": str(cat.id)}


class TestTenantIsolation:
    def test_cannot_read_other_tenant_employee(self, client, auth_headers, other_tenant):
        resp = client.get(f"/api/employees/{other_tenant['emp_id']}", headers=auth_headers)
        assert resp.status_code == 404

    def test_designation_rejects_other_tenant_department(self, client, auth_headers, other_tenant):
        resp = client.post("/api/org/designations", headers=auth_headers,
                           json={"name": "Spy", "department_id": other_tenant["dept_id"]})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid department_id"

    def test_designation_accepts_own_department(self, client, auth_headers):
        dept = client.post("/api/org/departments", headers=auth_headers,
                           json={"name": f"Own Dept {uuid.uuid4().hex[:4]}"}).get_json()
        resp = client.post("/api/org/designations", headers=auth_headers,
                           json={"name": "Engineer", "department_id": dept["department"]["id"]})
        assert resp.status_code == 201

    def test_malformed_reference_is_rejected(self, client, auth_headers):
        resp = client.post("/api/org/designations", headers=auth_headers,
                           json={"name": "Bad", "department_id": "not-a-uuid"})
        assert resp.status_code == 400

    def test_ticket_rejects_other_tenant_category(self, client, auth_headers, other_tenant):
        resp = client.post("/api/helpdesk/tickets", headers=auth_headers,
                           json={"title": "Laptop", "category_id": other_tenant["category_id"]})
        assert resp.status_code == 400

    def test_employee_update_rejects_other_tenant_manager(self, client, auth_headers,
                                                          seeded, other_tenant):
        emp_id = str(seeded["employee"].id)
        resp = client.put(f"/api/employees/{emp_id}", headers=auth_headers,
                          json={"reporting_manager_id": other_tenant["emp_id"]})
        assert resp.status_code == 400

    def test_feedback_rejects_other_tenant_reviewer(self, client, auth_headers, other_tenant):
        resp = client.post("/api/performance/feedback/request", headers=auth_headers,
                           json={"reviewer_ids": [other_tenant["emp_id"]]})
        assert resp.status_code == 400
