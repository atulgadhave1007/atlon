## What does this change?

<!-- One or two sentences. Link the issue: Closes #123 -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / tech debt
- [ ] Docs / tests only

## Checklist

- [ ] `cd backend && pytest tests/` passes locally
- [ ] Tests added or updated for this change
- [ ] Every new or changed route has `@require_auth(...)` (or a public route justified below)
- [ ] Every query filters by `tenant_id=g.tenant_id`; IDs from the request body are checked with `reject_foreign_refs`
- [ ] Cross-tenant test added for new endpoints (another tenant's ID returns 404 or 400)
- [ ] Money uses `Decimal`, not `float`
- [ ] User text goes through `sanitize_string()`
- [ ] Existing API response shapes are unchanged (or the change is explained below)
- [ ] No secrets, `.env`, database files or real personal data committed

## Notes for the reviewer

<!-- Payroll / statutory changes: cite the rule and show worked numbers. UI changes: add a screenshot taken with demo data. -->
