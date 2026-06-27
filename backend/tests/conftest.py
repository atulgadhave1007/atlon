import pytest
import os
from unittest.mock import patch

os.environ['FLASK_ENV'] = 'testing'
os.environ['SECRET_KEY'] = 'test-secret-key-32-chars-long-ok'
os.environ['JWT_SECRET'] = 'test-jwt-secret-key-32-chars-ok!'

from app import create_app
from app.config import TestingConfig
from app.extensions import db as _db


@pytest.fixture(scope='session', autouse=True)
def _suppress_email():
    """Prevent queue_email from touching Celery/Redis/SMTP in any test."""
    with patch('app.services.email_service.queue_email', return_value=None):
        yield


@pytest.fixture(scope='session')
def app():
    flask_app = create_app(TestingConfig)
    ctx = flask_app.app_context()
    ctx.push()
    _db.create_all()
    yield flask_app
    _db.drop_all()
    ctx.pop()


@pytest.fixture(scope='session')
def db(app):
    return _db


@pytest.fixture(scope='session')
def client(app):
    return app.test_client()


@pytest.fixture(scope='session')
def seeded(app, db):
    """Create one tenant + super admin + employee for use in tests. Idempotent."""
    from app.models import Plan, Tenant, SuperAdmin, Employee, PlanTier, TenantStatus, CountryCode
    from app.utils.security import hash_password
    from datetime import date

    try:
        plan = db.session.query(Plan).filter_by(name='standard').first()
        if not plan:
            plan = Plan(
                name='standard',
                tier=PlanTier.STANDARD, display_name='Standard',
                price_per_employee_inr=120, price_per_employee_usd=2,
                max_employees=500, max_admins=5,
                features={"attendance": True, "leave": True, "payroll": True}
            )
            db.session.add(plan)
            db.session.flush()

        tenant = db.session.query(Tenant).filter_by(slug='testco').first()
        if not tenant:
            tenant = Tenant(
                name='Test Co', slug='testco', email='admin@test.co',
                country=CountryCode.IN, status=TenantStatus.ACTIVE, plan_id=str(plan.id)
            )
            db.session.add(tenant)
            db.session.flush()

        super_admin = db.session.query(SuperAdmin).filter_by(email='superadmin@atlon.in').first()
        if not super_admin:
            super_admin = SuperAdmin(
                email='superadmin@atlon.in',
                password_hash=hash_password('Admin@123'),
                name='Super Admin'
            )
            db.session.add(super_admin)

        employee = db.session.query(Employee).filter_by(work_email='hradmin@test.co').first()
        if not employee:
            employee = Employee(
                tenant_id=str(tenant.id),
                employee_number='EMP001',
                first_name='Test',
                last_name='Admin',
                work_email='hradmin@test.co',
                password_hash=hash_password('Test@1234'),
                role='hr_admin',
                status='active',
                employment_type='full_time',
                date_of_joining=date(2023, 1, 1),
                force_password_change=False,
            )
            db.session.add(employee)

        db.session.commit()
        return {'tenant': tenant, 'employee': employee, 'super_admin': super_admin}

    except Exception:
        db.session.rollback()
        raise


@pytest.fixture(scope='session')
def auth_headers(client, seeded):
    """Get HR admin auth headers."""
    resp = client.post('/api/auth/login', json={
        'email': 'hradmin@test.co',
        'password': 'Test@1234',
        'slug': 'testco'
    })
    data = resp.get_json()
    token = data.get('access_token', '')
    return {'Authorization': f'Bearer {token}', 'X-Tenant-Slug': 'testco'}
