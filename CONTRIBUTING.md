# Contributing to Atlon HRMS

Thanks for your interest. Atlon handles salaries, tax IDs and bank details for many companies in one database, so the rules below aren't about style. They are what keeps one company's data away from another's.

## Development setup

```bash
git clone https://github.com/<your-fork>/atlon.git
cd atlon/backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py                   # http://localhost:5000
python seed_demo.py             # optional DEMO ONLY data (company "demo", EMP001 / Demo@1234)
pytest tests/                   # must pass before you open a PR
```

The frontend is a single file, `frontend/public/index.html`, with no build step. Flask serves it at `/` in development.

## Workflow

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Fork the repo and branch from `master`:
   - `feature/<short-name>` for new functionality
   - `fix/<short-name>` for bug fixes
3. Keep each PR to one logical change. Commit messages follow `verb(scope): description`, for example `fix(payroll): cap PF at the wage ceiling`.
4. Add or update tests, run `pytest tests/`, and fill in the pull request template.
5. CI must be green before review.

## Rules that every change must follow

### 1. Tenant isolation (never violate)
- Every query filters by tenant: `Model.query.filter_by(tenant_id=g.tenant_id, is_deleted=False)`.
- `tenant_id` always comes from `g.tenant_id`, which the middleware and auth set. Never take it from the request body, query string or JWT claims.
- **IDs sent by the client must belong to the caller's tenant.** If an endpoint stores a foreign key from the request body (`department_id`, `employee_id`, `reviewer_ids`...), check it first:

  ```python
  from app.utils.tenant_refs import reject_foreign_refs

  err = reject_foreign_refs(data, {"department_id": "Department", "reporting_manager_id": "Employee"})
  if err:
      return err
  ```
- Employees may only read or change their own records unless their role allows more (`hr_admin`, `payroll_admin`, or `manager` for their own team).

### 2. Authentication
- Every route has `@require_auth()` (optionally with `roles=[...]`) or `@require_super_admin`.
- Public routes are the exception and must be justified in the PR (current list: login, refresh, plans, signup, tenant branding, job applications, ZKTeco device endpoints).
- Never add a master password, backdoor or "debug" bypass.

### 3. Money
- Use `Decimal` for every amount: `Decimal(str(value))`. Never `float`.
- Round with `ROUND_HALF_UP` to 2 decimal places, as `payroll_engine._round()` does.

### 4. Input and output
- Pass user-supplied text through `sanitize_string(value, max_len)` before storing it.
- In the SPA, treat every server value as untrusted when building HTML.
- Parse enums inside `try/except ValueError` and return 400 on bad values. Normalise case first (`.lower()`).

### 5. Flask conventions
- Define specific routes (`/me`, `/my-*`, `/admin/*`) **before** wildcard routes (`/<id>`).
- Return `jsonify(...)`, and include `id` or `message` in success responses (the frontend checks for them).
- After a write to an employee, return `_emp_detail(emp)`, not `_emp_summary(emp)`.
- Don't change the shape of existing API responses without discussing it first. The SPA depends on them.

### 6. Tests are required
- New endpoints need tests for success, permission denied (wrong role) and **cross-tenant access** (another tenant's ID must give 404 or 400).
- Payroll or statutory changes need tests with worked numbers that cite the rule (the act, the circular, or the official calculator).
- See `backend/tests/test_security.py` for tenant-isolation test patterns.

### 7. Secrets and data
- Never commit `.env`, `*.db`, uploads, or screenshots that contain real people's data.
- Use only the demo tenant in screenshots, fixtures and issues.

## Reporting bugs and security issues

- Bugs and feature requests: use the GitHub issue templates.
- **Security vulnerabilities: do not open a public issue.** Follow [SECURITY.md](SECURITY.md).

## License of contributions

Atlon is licensed under the [GNU AGPL-3.0](LICENSE). By submitting a pull request, you agree that your contribution is licensed under the same terms.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind and assume good intent.
