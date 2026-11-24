# Atlon HRMS: Project Status

> **Last scanned:** 2026-11-24, from the source code on branch `open-source-prep`
> Every statement here comes from reading the code or running it. Nothing is taken from older planning docs.
> (Earlier versions of this file marked every module "✅ Done / Full". That was not accurate, and this version replaces it.)

---

## 1. Overview

Atlon is a self-hostable, multi-tenant HRMS and payroll system for small and mid-sized companies. It covers India statutory payroll (PF, ESI, PT, TDS, Form 16, ECR) and has basic UAE and US payroll engines. It is early-stage software that one person maintains.

### Tech stack (verified)

| Layer | Technology |
|---|---|
| Backend | Python 3.10+ / Flask 3.1, SQLAlchemy 2 (Flask-SQLAlchemy 3.1), Flask-Limiter, Flask-CORS |
| Auth | PyJWT (HS256), 15-minute access token, 30-day refresh token stored hashed (SHA-256) in the database, TOTP MFA (pyotp), bcrypt |
| Database | SQLite (dev, default `data/atlon.db`), PostgreSQL 16 (Docker Compose) |
| Background jobs | Celery 5.4 + Redis 7 (worker + beat) |
| PDF / exports | ReportLab (payslip, Form 16), CSV/XML generators (PF ECR, ESI, WPS SIF, NEFT, Tally) |
| Frontend | Vanilla JS single-page app (`frontend/public/index.html`, about 7,600 lines, no build step) and `landing.html` |
| Infra | Dockerfile (gunicorn), `docker-compose.yml` (backend, worker, beat, Postgres, Redis, nginx, certbot), `nginx/hrms.conf` (wildcard subdomain + TLS) |
| Tests | pytest, pytest-flask, Locust load script (`backend/locustfile.py`) |

### Size

- 25 Flask blueprints, **243 routes** (counted from route decorators)
- 17 model files
- 5 services, 5 Celery task modules (7 beat schedules)
- 74 SPA page handlers (`Pages[...]` in `index.html`)

---

## 2. Module status

Status key: **Complete** means the CRUD and workflow exist end to end (API and UI). **Partial** means it works but has known gaps listed in the notes. **Stub** means the code exists but is not wired up or not usable.

| Module | Backend file(s) | Routes | Status | Notes |
|---|---|---|---|---|
| Auth | `api/v1/auth.py`, `utils/auth.py` | 8 | Complete | Login (tenant + employee number or email), refresh, logout, me, change password, MFA setup/verify/disable. Login is rate limited (10 per 5 min). |
| Multi-tenancy | `middleware/tenant.py`, `models/tenant.py` | – | Complete | Tenant comes from the `X-Tenant-Slug` header or the subdomain. Authenticated requests take `g.tenant_id` from the employee record in the JWT. |
| Tenant settings | `api/v1/tenant.py` | 3 | Complete | The public `/info/<slug>` returns branding for the login page. |
| Super admin | `api/v1/super_admin.py` | 5 | Partial | Stats, tenant list/create/suspend, plans. No UI for managing super admins. |
| Billing | `api/v1/billing.py`, `tasks/billing_tasks.py` | 6 | Partial | Plans, self-signup with a 14-day trial, invoices, mark-paid (manual). **No Razorpay or Stripe integration or webhooks**, although the config keys exist. |
| Employees | `api/v1/employees.py` | 19 | Complete | Profile (50+ fields), photo upload, documents, bulk import, birthdays/anniversaries/wishes, org chart, profile-change requests. |
| Organization | `api/v1/organization.py` | 11 | Complete | Departments, designations, branches, policies, cost centers. |
| Attendance | `api/v1/attendance.py`, `tasks/attendance_tasks.py` | 21 | Complete | Check-in/out, monthly view, WFH, regularization, roster, shifts, holidays, team view, admin summary/export, bulk import, nightly absent marking. |
| Biometric | `api/v1/biometric.py` | 7 | Partial | ZKTeco iClock push protocol and device registry. Device calls are authenticated **only by the serial number** (see Security). Server timezone is hard-coded to Asia/Kolkata in the handshake. |
| Leave | `api/v1/leave.py`, `tasks/leave_tasks.py` | 12 | Complete | Types, balances, apply/review, approvals, accrual (monthly Celery job), comp-off, summary, team calendar, balance expiry. |
| Payroll | `api/v1/payroll.py`, `services/payroll_engine.py` | 26 | Partial | Salary structure, components, payroll run and lock, payslips and PDF, tax declaration, Form 16, statutory exports, salary advances. See section 3 for country gaps. |
| Performance | `api/v1/performance.py` | 21 | Complete | Appraisal cycles, self/manager appraisal, KRAs, goals, 360° feedback, increments. Also has OKR endpoints (duplicated by `okr.py`). |
| OKR | `api/v1/okr.py` | 4 | Partial | Objectives, key results, check-ins. Overlaps with `/api/performance/okr/*`. |
| Recruitment | `api/v1/recruitment.py` | 7 | Partial | Jobs, publish, applications, pipeline move, interviews, public apply endpoint. No public careers page, offer workflow or resume parsing. |
| Training (LMS) | `api/v1/training.py` | 8 | Partial | Courses, enrolment, progress. Also has survey endpoints (duplicated by `surveys.py`). No course content or player. |
| Surveys | `api/v1/surveys.py` | 5 | Partial | Create, publish, respond, results. |
| Expense & travel | `api/v1/expense.py` | 11 | Complete | Categories, claims with line items, submit/approve, travel requests. Also has asset endpoints (duplicated by `assets.py`). |
| Assets | `api/v1/assets.py` | 6 | Partial | CRUD, assign, return, my assets. Audit log calls use the wrong argument order (see bugs). |
| Helpdesk | `api/v1/helpdesk.py` | 18 | Complete | Tickets with SLA from category, comments, resolve, HR Connect, Innovation Kiosk, announcements and acknowledgements, visitors (duplicated by `visitors.py`). |
| Visitors | `api/v1/visitors.py` | 4 | Partial | Register, check in, check out. |
| Timesheets | `api/v1/timesheets.py` | 4 | Partial | Create, submit, approve. |
| Exit & FnF | `api/v1/exit.py` | 13 | Complete | Initiate, withdraw, approve, clearance checklist, exit interview, FnF calculation (manual amounts), complete. |
| Lifecycle | `api/v1/lifecycle.py` | 5 | Complete | Confirmation, transfer, promotion (with new CTC), event history. |
| Letters | `api/v1/letters.py` | 6 | Complete | Letter requests, offer letters, experience letters, salary certificates, appraisal letters (template placeholders). |
| Notifications | `api/v1/notifications.py`, `utils/notifications.py`, `tasks/notification_tasks.py` | 6 | Partial | In-app notifications, config, audit-log view. Email via SMTP + 9 HTML templates. WhatsApp Cloud API sender exists but is untested. Birthday/anniversary Celery jobs. |
| Reports | `api/v1/reports.py` | 7 | Partial | Headcount, attendance summary, payroll register (+ CSV export), generic `/<report_type>`, AMS dashboard. |

---

## 3. Payroll coverage by country

### India (`IndiaPayrollEngine`): mostly implemented

| Item | Status | Detail |
|---|---|---|
| PF (EPF/EPS) | ✅ | 12% employee; employer 8.33% EPS + 3.67% EPF; ₹15,000 wage ceiling; EDLI 0.5%, admin 0.5% |
| ESI | ✅ | 0.75% / 3.25% below the ₹21,000 gross ceiling |
| Professional Tax | ⚠️ Partial | Slabs only for MH, KA, TN, WB and a DEFAULT. Other states fall back to DEFAULT. The MH February ₹300 rule is not modelled. |
| TDS | ⚠️ Partial | **New regime only** (FY 2025-26 slabs, ₹75,000 standard deduction, 4% cess). No old regime, no surcharge. Declarations are stored but not used in the calculation. **Bug to verify:** the 87A rebate cut-off is ₹7,00,000 (the FY 2024-25 value), but the slabs are FY 2025-26, where the rebate cut-off is ₹12,00,000. |
| LOP proration | ✅ | paid_days / total_days |
| Form 16 PDF | ✅ | `services/form16_generator.py` (single + bulk ZIP). 0% test coverage. |
| PF ECR, ESI return, NEFT bulk file, Tally XML | ✅ | `services/statutory_exports.py`. 0% test coverage, formats not checked against the official portals. |
| Gratuity (India) | ❌ | Not implemented. FnF amounts are entered by hand. |

### UAE (`UAEPayrollEngine`): basic

| Item | Status | Detail |
|---|---|---|
| Earnings | ✅ | Basic, housing, transport, other allowances, prorated |
| Deductions / GPSSA | ❌ | Not computed (code comment says so) |
| Gratuity | ⚠️ | 21 days/yr for the first 5 years, then 30 days/yr. It also applies resignation reductions (1/3, 2/3), which follow the **pre-2022 labour law**. Check this against Federal Decree-Law 33/2021. |
| WPS SIF export | ✅ | `generate_wps_sif`, untested |

### US (`USPayrollEngine`): simplified

| Item | Status | Detail |
|---|---|---|
| Social Security | ⚠️ | 6.2%. The wage base is 168,600 (the 2024 figure), and **year-to-date gross is always 0**, so the wage base cap is never applied across months. |
| Medicare | ✅ | 1.45% + 0.9% additional over $200k (annualised estimate) |
| Federal income tax | ⚠️ | 2025 single-filer brackets on annualised gross. No W-4, filing status, pre-tax deductions or standard deduction. |
| State / local tax | ❌ | Not implemented |
| Employer FUTA/SUTA | ❌ | Not implemented |

**Money handling:** the engines calculate in `Decimal` but return `float` in their result dicts. Several API handlers parse money with `float()` (`exit.py` FnF, `expense.py` claims, `payroll.py` advances, `lifecycle.py` promotion CTC), which breaks the project's own "Decimal for money" rule.

---

## 4. Frontend status

- `index.html`: 74 page handlers. 73 are reachable from the sidebar. `change-password` is the only nav target with no handler, so it falls back to the "Coming Soon" screen.
- API usage, measured by calls per resource prefix: employees 29, leave 20, attendance 19, payroll 15, helpdesk 15, org 9, performance 7, exit 7, expense 6, super 6, auth 6, visitors 5, timesheets 4, okr 4, plus surveys, recruitment, notifications, letters, tenant, reports, training and assets.
- Pages with no API call in their own block: `expenses` and `statutory`. These are menu/landing screens that link to sub-pages.
- **No HTML-escaping helper exists.** Server data is put into the page with `innerHTML` in 91 places (see Security).
- Access and refresh tokens are kept in `localStorage`.
- `landing.html`: static marketing page (470 lines).

---

## 5. Test status

Command: `cd backend && pytest tests/`

| Metric | Value |
|---|---|
| Baseline (before this prep work) | **102 passed, 1 skipped, 0 failed** |
| Test files | `test_auth.py` (9), `test_employees.py` (7), `test_attendance.py` (11), `test_payroll.py` (10), `test_payroll_integration.py` (66) |
| Line coverage (`pytest --cov=app`) | **≈52 %** overall |
| Well covered | payroll_engine 98%, models ~100%, config, middleware |
| No tests at all | leave, performance, OKR, recruitment, training, surveys, expense, assets, helpdesk, visitors, timesheets, exit, lifecycle, letters, notifications, reports, billing, super admin, biometric (route coverage 17–43%, from shared fixtures only) |
| 0 % coverage | Celery tasks, Form 16, statutory exports, storage service, WhatsApp/notifications util |

---

## 6. Security review findings

| # | Finding | Severity | Status |
|---|---|---|---|
| S1 | Hard-coded super admin password `AtlonAdmin@123` used as a config fallback and auto-created on startup; also in `.env.example`, `CLAUDE.md`, seed output | Critical | Fixed in Phase 3 |
| S2 | Default `SECRET_KEY` / `JWT_SECRET` fallbacks accepted in production | Critical | Fixed in Phase 3 |
| S3 | CORS defaults to `*` | High | Fixed in Phase 3 (production refuses wildcard) |
| S4 | `seed_demo.py` can run against production | Medium | Fixed in Phase 3 |
| S5 | `require_auth` accepted a super-admin JWT without checking that the super admin still exists and is active | High | Fixed in Phase 3 |
| S6 | Cross-tenant references: foreign-key IDs taken from request bodies (e.g. `category_id`, `employee_id`, `reporting_manager_id`, `reviewer_ids`) were stored without checking that the row belongs to the caller's tenant | High | Fixed in Phase 3 (see section 10) |
| S7 | Every route has `@require_auth` / `@require_super_admin` **except** intentionally public ones: login, refresh, `/billing/plans`, `/billing/signup`, `/tenant/info/<slug>`, `/recruitment/jobs/<id>/apply`, ZKTeco `/biometric/iclock/*`, `/employees/uploads/photos/<file>` | Info | Reviewed |
| S8 | Every query keyed on a URL path parameter filters by `tenant_id` (checked with an AST scan of all 243 routes) | Info | Verified OK |
| S9 | ZKTeco iClock endpoints trust the device serial number with no shared secret, so anyone who knows a registered SN can push fake punches | Medium | Open (P1) |
| S10 | Employee photos served without auth (`/api/employees/uploads/photos/<file>`); file names are UUID-based | Low | Open (P1) |
| S11 | No HTML escaping in the SPA (91 `innerHTML` sinks), and `sanitize_string()` is used in only 9 of 25 blueprints. Stored XSS is possible, and since tokens live in `localStorage` an XSS could steal sessions | High | Open (**P1**) |
| S12 | Rate limiting: global 200/min, login 10/5 min (Flask-Limiter), plus nginx `limit_req`. The dev config uses in-memory storage | Info | OK |
| S13 | Security headers set (nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy). No CSP or HSTS | Low | Open (P2) |
| S14 | Real secrets in git history: none found. `backend/.env` and `data/atlon.db` are git-ignored and were never committed. The only committed credential is `AtlonAdmin@123` (and the demo password `Demo@1234`) | Info | See rotation note |

---

## 7. Infrastructure status

| Component | Status | Notes |
|---|---|---|
| Dockerfile | ✅ | python:3.12-slim + gunicorn (4 workers × 2 threads) |
| docker-compose | ✅ | backend, worker, beat, Postgres 16, Redis 7, nginx, certbot (profile `ssl`). Needs `POSTGRES_PASSWORD` in a root `.env`. No backend healthcheck. |
| nginx | ✅ | `*.atlon.in` wildcard TLS, API and login rate limits, static caching, biometric passthrough. The domain is hard-coded, so self-hosters must edit it. |
| Celery | ⚠️ | 7 beat jobs. **`app.tasks.helpdesk_tasks.send_overdue_ticket_reminders` is scheduled but the module does not exist.** |
| Migrations | ❌ | `backend/migrations/` is empty. Schema is created with `db.create_all()` on startup, plus hand-written SQLite patches in `_apply_sqlite_migrations()`. On PostgreSQL, schema changes to existing tables are **not** applied. |
| CI | ✅ added | `.github/workflows/ci.yml` (Phase 4) |

---

## 8. Known bugs and TODOs found in code

- `services/payroll_engine.py`: 87A rebate cut-off does not match the slab year (see section 3).
- `services/payroll_engine.py`: US year-to-date gross is hard-coded to 0, so the Social Security wage base never caps.
- `tasks/celery_app.py`: beat schedule references the missing `app.tasks.helpdesk_tasks`.
- `api/v1/assets.py` (3×), `okr.py`, `surveys.py` (2×), `timesheets.py` (2×): `log_action(g.tenant_id, g.employee.id, ...)` passes arguments in the wrong order, so audit rows get garbage `action` / `entity_type`. `log_action` swallows all exceptions, so nobody notices.
- `api/v1/employees.py:575`: `status` filter on `/profile-requests` is silently ignored (`pass`).
- `api/v1/performance.py` `create_goal`: any employee can create a goal for any `employee_id` in their own tenant.
- Duplicate endpoints for the same feature in two places: OKR (`performance.py` + `okr.py`), surveys (`training.py` + `surveys.py`), assets (`expense.py` + `assets.py`), visitors (`helpdesk.py` + `visitors.py`).
- Legacy `Query.get()` calls (SQLAlchemy 2 deprecation warnings).
- SQLAlchemy warning: FK cycle between `departments`, `designations` and `employees` (needs `use_alter=True`).
- SPA: `change-password` nav target has no page handler.
- No `TODO`/`FIXME` markers in backend code. 3 bare `pass` blocks are deliberate `except: pass` swallows (attendance.py ×2, employees.py).

---

## 9. Roadmap

### P0: before making the repo public
- [x] Remove hard-coded super admin credentials; env-based bootstrap
- [x] Refuse default secrets and wildcard CORS in production
- [x] Seed script refuses production; demo credentials labelled
- [x] Tenant-ownership checks on body-supplied foreign keys
- [x] README, LICENSE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, templates, CI
- [ ] Owner decision on third-party UI references (Stratemis): see the Phase 5 notes
- [ ] Rotate any credential ever committed (`AtlonAdmin@123` on any running instance)

### P1: next
- Escape all server data in the SPA (an `esc()` helper on every `innerHTML` template) and apply `sanitize_string()` across the remaining blueprints
- Move tokens out of `localStorage` (httpOnly refresh cookie)
- Shared secret / allow-list for ZKTeco devices
- Fix payroll bugs (87A rebate, US YTD wage base) and use `Decimal` end to end in money APIs
- Create the missing `helpdesk_tasks` module or remove the schedule
- Generate an initial Alembic migration; stop relying on `create_all()` in production
- Tests for leave, performance, exit, expense, helpdesk, Form 16 and statutory exports
- Fix `log_action` argument order in assets/okr/surveys/timesheets

### P2: later
- Old tax regime, surcharge, more PT states; UAE GPSSA; US state tax and W-4
- Razorpay / Stripe webhooks
- Remove duplicate endpoints (OKR, surveys, assets, visitors)
- CSP and HSTS headers; nginx domain made configurable
- Public careers page, workflow engine, SSO (see `TODO.md`)

---

## 10. Changes made during open-source prep (2026-11-24)

See the Phase 6 section below, which is filled in after verification.
