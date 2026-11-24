# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Atlon HRMS is an open-source (AGPL-3.0), self-hostable, multi-tenant HRMS. It supports India statutory payroll plus basic UAE and US payroll. Verified module status, known bugs and the roadmap live in `PROJECT_STATUS.md`.

## Repository Layout
```
atlon hrms/
  backend/
    app/
      api/v1/          # 25 Flask blueprints (one per domain)
      models/          # 17 SQLAlchemy model files
      services/        # payroll_engine.py, celery tasks
      middleware/      # tenant.py (slug from subdomain or X-Tenant-Slug header)
      utils/           # auth.py (require_auth, log_action), security.py (sanitize_string)
      extensions.py    # db, migrate, cors, limiter
      __init__.py      # create_app(), _register_blueprints()
    seed_demo.py       # DEMO ONLY seed: tenant slug=demo (refuses to run in production)
    tests/             # pytest suite lives here (inside backend/)
    requirements.txt
    run.py
  frontend/
    public/
      index.html       # ~7600-line Vanilla JS SPA (tile-based ESS dashboard)
      landing.html     # Marketing page
```

## Stack
- **Backend**: Flask 3.1, SQLAlchemy 2, SQLite (dev) / PostgreSQL (prod), Celery + Redis
- **Frontend**: Vanilla JS SPA, no build step, served by Flask or nginx
- **Auth**: JWT (access 15min + refresh 30d), `X-Tenant-Slug` header for dev, subdomain in prod
- **Multi-tenancy**: `tenant_id` column on every table, resolved in middleware before every request

## Development Commands

```bash
# Run the app
cd backend
pip install -r requirements.txt
cp .env.example .env         # placeholders only; set SUPER_ADMIN_EMAIL (password is generated once in dev if empty)
python seed_demo.py          # optional, DEMO ONLY — creates demo tenant + employees
python run.py                # http://localhost:5000 (serves frontend too)

# Run all tests
cd backend
pytest tests/ -v

# Run a single test file
pytest tests/test_auth.py -v

# Run a specific test
pytest tests/test_payroll.py::TestPayroll::test_gross_salary_calculation -v

# Database migrations (PostgreSQL)
flask db migrate -m "description"
flask db upgrade

# Celery worker (for background tasks)
celery -A app.tasks.celery_app worker --loglevel=info

# Celery beat (for scheduled tasks: daily absent marking, leave accrual, etc.)
celery -A app.tasks.celery_app beat --loglevel=info
```

## Demo Credentials (DEMO ONLY, after running seed_demo.py)
```
Company ID : demo
HR Admin   : EMP001 / Demo@1234
Manager    : EMP003 / Demo@1234
Employee   : EMP005 / Demo@1234
```
These are publicly known. Never seed a database real people use.
There is **no default super admin**: it is created on first start from
`SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` (see Startup Behavior). Never hard-code credentials.

## Critical Rules — Always Follow

### 1. Tenant Isolation (NEVER violate)
- Every DB query MUST include `.filter_by(tenant_id=g.tenant_id)`
- Every route MUST have `@require_auth()` decorator
- `g.tenant_id`, `g.employee`, `g.role` are set by middleware — use them
- IDs that arrive in a request body (`department_id`, `employee_id`, `reviewer_ids`...) must be checked
  with `reject_foreign_refs(data, {"field": "ModelName"})` from `app/utils/tenant_refs.py` before storing

### 2. Route Ordering
- Specific routes MUST be defined BEFORE wildcard `/<id>` routes in Flask blueprints
- Pattern: `/me`, `/my-*`, `/admin/*` always come before `/<emp_id>`

### 3. Auth Decorator Pattern
```python
@blueprint.route("/path", methods=["GET"])
@require_auth(roles=["employee", "manager", "hr_admin"])  # omit roles= for any authenticated user
def handler():
    emp = g.employee        # current employee
    tenant_id = g.tenant_id # current tenant
    role = g.role           # "employee" | "manager" | "hr_admin" | "payroll_admin"
```

### 4. Response Conventions
- Always return `jsonify({...})` — never raw dicts (Flask 3.x compatibility)
- Frontend checks `res?.id || res?.message` for success — always include one of these
- For employee responses: use `_emp_detail(emp)` for full profile (50+ fields), `_emp_summary(emp)` for list views only (9 fields). **Using `_emp_summary` on a save response breaks the form** — always use `_emp_detail` when returning after a write.

### 5. Never Do
- Business logic inside route handlers (use service layer)
- Hardcoded tenant IDs, employee IDs, or salaries
- Bypass `is_deleted=False` filter
- Skip `sanitize_string()` on user text input
- Placeholder/demo/TODO implementations

## Models Quick Reference
```
Employee          → employees table, custom_fields JSON for non-standard fields
EmployeeSalary    → effective_to=None means "current"
LeaveApplication  → from_date (NOT start_date), to_date
AppraisalCycle    → period_from / period_to (NOT period_start/period_end)
HelpTicket        → tags=["innovation"] or tags=["hr-connect"] for sub-types
Attendance        → status enum: PRESENT/ABSENT/HALF_DAY/LATE/ON_LEAVE/WORK_FROM_HOME/etc.
ExitStatus        → includes WITHDRAWN (added manually, not in original enum)
```

## ORM Patterns

```python
# BaseModel provides .active() class method for soft-delete filter
Employee.query.filter_by(tenant_id=g.tenant_id).active()  # NOT .filter_by(is_deleted=False)
# or equivalently:
Employee.active().filter_by(tenant_id=g.tenant_id)

# UUIDs come back as uuid.UUID objects — always str() when serializing
"id": str(record.id)

# Money: always Decimal, never float
from decimal import Decimal
amount = Decimal(str(data.get("amount", 0)))

# Enums: always try/except, enum values stored lowercase in DB
try:
    status = SomeStatus(data.get("status", ""))
except ValueError:
    return jsonify({"error": "Invalid status"}), 400
```

## Frontend API Helper Pattern
```javascript
const GET   = (path, params, opts) => api('GET', path, params, opts);
const POST  = (path, body, opts)   => api('POST', path, body, opts);
const PATCH = (path, body, opts)   => api('PATCH', path, body, opts);
// All calls prepend API_BASE (/api) and inject Authorization + X-Tenant-Slug headers
// For page-load GETs: always pass {silent:true} and provide a fallback:
const data = await GET('/endpoint', {}, {silent: true}) || {};
const items = data?.items || [];
```

## Common Bug Patterns to Avoid
- **Field name mismatch**: Frontend form key != backend's expected key → silent 200 with no DB write. Always verify both sides use the same key name. Field alias maps exist in `employees.py` for known mismatches.
- **`_emp_summary` vs `_emp_detail`**: Never return `_emp_summary` from write endpoints — it only has 9 fields and will blank out all profile data on the frontend after save.
- **Enum case**: Frontend sends `"Male"` → backend enum expects `"male"`. Normalize with `.lower()` before enum parsing.
- **Profile page data source**: Always load profile from `GET /employees/me` (50+ fields), not `GET /auth/me` (9 fields).

## Startup Behavior
`create_app()` auto-runs `_apply_sqlite_migrations()` on every startup to patch SQLite schema drift (column nullability fixes that `db.create_all()` won't apply to existing tables). This is a no-op on PostgreSQL. It also auto-seeds billing plans and bootstraps the first super admin
(`_bootstrap_super_admin`): from `SUPER_ADMIN_EMAIL`/`SUPER_ADMIN_PASSWORD`; with no password, development
generates one and prints it once, production creates none. In production (`FLASK_ENV=production`) the app
refuses to start with placeholder/short `SECRET_KEY`/`JWT_SECRET` or wildcard `CORS_ORIGINS`.

## Agents Available
Invoke with `@agent_name` in your prompt:
- `@architect` — architecture decisions, module design, refactoring plans
- `@backend` — Flask routes, SQLAlchemy, APIs
- `@frontend` — Vanilla JS SPA, UI components
- `@hr` — HR domain logic, workflows, compliance
- `@payroll` — payroll calculations, PF/ESI/TDS, multi-country
- `@attendance` — shift logic, biometric, roster, overtime
- `@security` — auth, RBAC, multi-tenant isolation audits
- `@test` — pytest, integration tests, coverage
- `@docs` — API documentation, architecture docs
- `@devops` — Docker, nginx, CI/CD, deployment

## Slash Commands Available
- `/audit`          — full codebase audit (security, architecture, SQL)
- `/api-docs`       — generate API_REFERENCE.md from blueprints
- `/generate-tests` — generate pytest suite for a module
- `/fix-bugs`       — find and fix 404/500 errors, URL mismatches
- `/refactor`       — refactor module for clarity and DRY
- `/analyze`        — analyze repo structure and suggest improvements
- `/seed`           — guidance on seeding/resetting demo data
- `/status`         — print current build status tracker
