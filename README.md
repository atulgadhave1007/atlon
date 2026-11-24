# Atlon HRMS

[![CI](https://github.com/atulgadhave1007/atlon/actions/workflows/ci.yml/badge.svg)](https://github.com/atulgadhave1007/atlon/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

**An open-source, self-hostable, multi-tenant HRMS with Indian statutory payroll, plus basic UAE and US payroll.**

Small and mid-sized companies in India mostly use closed-source HR software that charges per employee per month. There are open-source HR tools, but few of them handle Indian statutory payroll (PF, ESI, Professional Tax, TDS, Form 16, PF ECR) together with day-to-day HR work, and fewer still can host many companies from one deployment. Atlon is an attempt to fill that gap.

> **Status: early-stage, single maintainer.** Most modules work end to end, and some are partial. Payroll output is **not** a substitute for review by a qualified payroll professional. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for a module-by-module status, known bugs, and open security items.

---

## Features

Everything listed here exists in the code today. Gaps are noted in brackets.

**Core HR**
- Multi-tenant: one deployment hosts many companies. The tenant is resolved from the subdomain (`acme.example.com`) or the `X-Tenant-Slug` header, and every table carries a `tenant_id`.
- Employee profiles (50+ fields), documents, photo, education, family, previous employment, bulk import, org chart
- Departments, designations, branches, cost centres, policies
- Lifecycle events: confirmation, transfer, promotion with salary revision
- Letters: offer, experience, salary certificate, appraisal letters
- Exit management: resignation, approval, clearance checklist, exit interview, full and final settlement (FnF amounts are entered by hand)

**Time & attendance**
- Check-in/out, WFH requests, regularisation, shifts, rosters, holiday calendar, team and admin views, CSV export
- ZKTeco biometric devices over the iClock push protocol
- Nightly absent marking (Celery)

**Leave**
- Leave types, balances, apply/approve, comp-off, team calendar, monthly accrual and expiry (Celery)

**Payroll**
- Salary structures and components, payroll runs with locking, payslips with PDF, tax declarations, salary advances
- **India:** PF (EPF/EPS with the ₹15,000 ceiling, EDLI, admin charges), ESI, Professional Tax (MH, KA, TN, WB and a default slab), TDS under the new regime, Form 16 PDF, PF ECR, ESI return, NEFT bulk file, Tally XML
- **UAE:** allowance-based payroll, end-of-service gratuity, WPS SIF file *(no GPSSA)*
- **US:** Social Security, Medicare, simplified federal withholding *(no state tax or W-4 handling)*

**Talent & engagement**
- Appraisal cycles, self and manager reviews, KRAs, goals, 360° feedback, increments, OKRs
- Recruitment: job postings, applications, pipeline stages, interviews *(no public careers page yet)*
- Training courses and enrolment, surveys

**Operations**
- Helpdesk tickets with SLAs, HR Connect, Innovation Kiosk, announcements
- Expense claims and travel requests, asset management, visitor management, timesheets
- In-app notifications, SMTP email with HTML templates, birthday and anniversary jobs
- Reports: headcount, attendance summary, payroll register (CSV)

**Platform**
- JWT auth (15-minute access tokens, rotating refresh tokens), TOTP MFA, account lockout, password policy, audit log
- Super-admin console: tenants, plans, self-serve signup with trial *(no payment-gateway integration yet)*

## Screenshots

> **TODO (maintainer):** add screenshots of the login page, ESS dashboard, payroll run and payslip here.
> Use only the demo tenant (`seed_demo.py`), never real employee data.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, Flask 3.1, SQLAlchemy 2, Flask-Limiter, Flask-CORS |
| Auth | PyJWT, bcrypt, pyotp (TOTP MFA) |
| Database | SQLite for development, PostgreSQL 16 for production |
| Background jobs | Celery 5 + Redis 7 |
| Documents | ReportLab (PDF), CSV / XML exporters |
| Frontend | Vanilla JavaScript single-page app, no build step |
| Deployment | Docker, docker-compose, gunicorn, nginx |
| Tests | pytest, pytest-flask, Locust (load) |

## Quick start (local, SQLite)

Requires Python 3.10 or newer.

```bash
git clone https://github.com/atulgadhave1007/atlon.git
cd atlon/backend

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # Windows: copy .env.example .env
python run.py                     # http://localhost:5000
```

The SQLite database is created at `data/atlon.db` on first start.

**Super admin.** On first start, Atlon creates one super admin from `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_PASSWORD` in `backend/.env`. In development, if `SUPER_ADMIN_PASSWORD` is empty, a random password is generated and **printed once** to the console. Copy it then, because it is not shown again. To log in as super admin, leave *Company ID* empty on the login page and use that email and password.

### Demo data (DEMO ONLY)

```bash
cd backend
python seed_demo.py
```

This creates a fake company (`demo`) with 10 employees, attendance, leave, payslips, tickets and expenses. All demo accounts share the **publicly known** password `Demo@1234`:

| Role | Company ID | Username |
|---|---|---|
| HR admin | `demo` | `EMP001` |
| Manager | `demo` | `EMP003` |
| Employee | `demo` | `EMP005` |

The script refuses to run when `FLASK_ENV=production`. Never seed a database that real people use.

## Docker Compose (production-style)

`docker-compose.yml` runs the backend (gunicorn), a Celery worker, Celery beat, PostgreSQL 16, Redis 7 and nginx with TLS.

1. Copy `.env.example` to `.env` in the repo root and set `POSTGRES_PASSWORD`.
2. Copy `backend/.env.example` to `backend/.env` and set at least `SECRET_KEY`, `JWT_SECRET` (two different random values of 32+ characters), `CORS_ORIGINS`, `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_PASSWORD`. With `FLASK_ENV=production`, the backend **refuses to start** on placeholder or short secrets or a wildcard CORS origin.
3. Edit `nginx/hrms.conf`. The domain is currently hard-coded to `*.atlon.in`, and nginx expects Let's Encrypt certificates for it. Replace it with your own domain and certificates (the `certbot` service is under the `ssl` profile).
4. `docker compose up -d --build`

Schema is created by `db.create_all()` on startup. There are **no Alembic migrations yet**, so schema changes to existing PostgreSQL tables are not applied automatically. See the roadmap.

## Configuration

Every variable is listed with placeholders in [`backend/.env.example`](backend/.env.example).

| Variable | Required | Description |
|---|---|---|
| `FLASK_ENV` | yes | `development`, `production` or `testing` |
| `SECRET_KEY` | prod | Flask secret. 32+ random characters, placeholders rejected in production |
| `JWT_SECRET` | prod | JWT signing key. 32+ random characters, must differ from `SECRET_KEY` |
| `CORS_ORIGINS` | prod | Comma-separated allowed origins. `*` is rejected in production |
| `SUPER_ADMIN_EMAIL` | first start | Email of the first super admin |
| `SUPER_ADMIN_PASSWORD` | prod first start | Password of the first super admin. If empty: dev generates one, production creates none |
| `DATABASE_URL` | prod | PostgreSQL URL. Defaults to SQLite at `data/atlon.db` |
| `REDIS_URL` | for Celery | Redis for Celery and rate limiting |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | no | Default to `REDIS_URL` |
| `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS` | no | Token lifetimes (defaults 15 min / 30 days) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `FROM_EMAIL`, `FROM_NAME` | for email | Outgoing mail |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN` | no | WhatsApp Cloud API notifications |
| `STORAGE_BACKEND`, `STORAGE_LOCAL_PATH`, `AWS_*` | no | `local`, `s3` or `minio` file storage |
| `BASE_DOMAIN`, `FRONTEND_URL` | prod | Domain used for tenant subdomains and links |
| `RAZORPAY_*`, `STRIPE_*` | no | Reserved. Gateways are not integrated yet |
| `SENTRY_DSN` | no | Error reporting |
| `POSTGRES_PASSWORD` | compose | In the **root** `.env`, used by `docker-compose.yml` |

## Project structure

```
atlon/
├── backend/
│   ├── app/
│   │   ├── api/v1/         # 25 Flask blueprints, one per domain (243 routes)
│   │   ├── models/         # SQLAlchemy models (every table has tenant_id)
│   │   ├── services/       # payroll engines, Form 16, statutory exports, email, storage
│   │   ├── tasks/          # Celery app + scheduled jobs
│   │   ├── middleware/     # tenant resolution, security headers
│   │   ├── utils/          # auth (require_auth), security (sanitize_string), tenant_refs
│   │   ├── templates/email/
│   │   ├── config.py
│   │   └── __init__.py     # create_app()
│   ├── tests/              # pytest suite
│   ├── seed_demo.py        # DEMO ONLY seed data
│   ├── locustfile.py       # load test
│   ├── run.py
│   └── requirements.txt
├── frontend/public/
│   ├── index.html          # single-page app
│   └── landing.html        # marketing page
├── nginx/hrms.conf
├── docker-compose.yml
└── PROJECT_STATUS.md       # verified status, known issues, roadmap
```

## Running tests

```bash
cd backend
pytest tests/                          # whole suite
pytest tests/test_security.py -v       # one file
pytest tests/ --cov=app                # with coverage (pip install pytest-cov)
```

Current state: **123 passed, 1 skipped**, about 52% line coverage. CI runs the suite on every push and pull request.

## Roadmap

The full prioritised list is in [PROJECT_STATUS.md](PROJECT_STATUS.md#9-roadmap). The next items are:

- **Security:** escape all server data in the SPA (stored-XSS hardening), move tokens out of `localStorage`, authenticate biometric devices with a shared secret
- **Payroll correctness:** fix the 87A rebate threshold and the US Social Security wage base, and use `Decimal` end to end in money APIs
- **Operations:** Alembic migrations for PostgreSQL, a configurable nginx domain
- **Tests:** leave, performance, exit, expenses, helpdesk, Form 16 and statutory exports
- **Later:** old tax regime, more Professional Tax states, UAE GPSSA, US state tax, payment-gateway webhooks

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), especially the tenant-isolation rules, and the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in [SECURITY.md](SECURITY.md), not in public issues.

## License

Copyright (C) 2026 Atul Gadhave

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT ANY WARRANTY. See [LICENSE](LICENSE) for the full text.

In short: you may use, modify and self-host Atlon. If you run a modified version as a network service, you must make your modified source code available to its users.
