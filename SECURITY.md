# Security Policy

Atlon stores payroll, tax-ID and bank-account data for many companies in one database. Security reports are very welcome and are treated as the top priority.

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for security problems.**

Report privately through GitHub:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** (GitHub private vulnerability reporting).
3. Include the affected endpoint or file, the steps to reproduce, the impact (for example "an HR admin of tenant A can read tenant B's payslips"), and a suggested fix if you have one.

Only the maintainer (Atul Gadhave) can see the report.

### What to expect

- Acknowledgement within **7 days**.
- An assessment and a planned fix date within **14 days** of acknowledgement.
- Credit in the release notes once a fix is released, unless you ask to stay anonymous.

This is a volunteer project with a single maintainer, so these are good-faith targets rather than guarantees.

## Supported versions

Atlon has no tagged releases yet. Fixes go to the `master` branch only.

## In scope

- Cross-tenant data access (reading or changing another company's records)
- Authentication or authorization bypass, privilege escalation between roles
- Injection (SQL, template), stored or reflected XSS, CSRF on state-changing endpoints
- Exposure of salaries, bank details, PAN/Aadhaar/Emirates ID or password hashes
- Insecure defaults in the shipped configuration

## Out of scope

- Findings that require a compromised server or a malicious super admin
- Denial of service from very high request volume
- Issues in deployments that ignore the production checks (for example running with `FLASK_ENV=development` on the internet)
- Missing hardening that is already listed as an open item in [PROJECT_STATUS.md](PROJECT_STATUS.md#6-security-review-findings)

## Known open security items

Open hardening work is tracked publicly in [PROJECT_STATUS.md](PROJECT_STATUS.md#6-security-review-findings): SPA output escaping, token storage, and biometric device authentication. Reports that show a concrete exploit for any of these are still welcome.

## Safe harbour

Good-faith research is welcome. Test only against your own installation, never against someone else's deployment, and do not access, keep or share other people's data. If you follow this policy, no legal action will be taken against you.
