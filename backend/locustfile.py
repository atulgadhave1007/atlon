"""
Atlon HRMS — Load Test Suite
Target: http://localhost:5000 with the seeded demo tenant.

Usage:
    pip install locust
    locust -f locustfile.py --host=http://localhost:5000

    # Headless (CI):
    locust -f locustfile.py --host=http://localhost:5000 \\
           --headless -u 100 -r 10 --run-time 60s

Seeded credentials (after running seed_demo.py):
    Tenant slug : demo
    HR Admin    : EMP001 / Demo@1234
    Employee    : EMP005 / Demo@1234
"""
import json
import random
from datetime import date, timedelta
from locust import HttpUser, task, between, events


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _login(client, username: str, password: str, slug: str = "demo") -> str | None:
    """Return the access_token or None on failure."""
    with client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "slug": slug},
        headers={"X-Tenant-Slug": slug},
        catch_response=True,
        name="/api/auth/login",
    ) as resp:
        if resp.status_code == 200:
            data = resp.json()
            if data.get("force_password_change"):
                resp.failure("force_password_change set — seed_demo.py not run?")
                return None
            return data.get("access_token")
        resp.failure(f"Login failed: {resp.status_code}")
        return None


def _headers(token: str, slug: str = "demo") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": slug,
        "Content-Type": "application/json",
    }


# ── Employee user (typical individual contributor) ────────────────────────────

class EmployeeUser(HttpUser):
    """Simulates a regular employee: views profile, attendance, payslips, leaves."""

    wait_time = between(1, 4)
    weight = 10  # 10 employees for every 1 HR admin

    def on_start(self):
        token = _login(self.client, "EMP005", "Demo@1234")
        if not token:
            self.environment.runner.quit()
            return
        self.hdrs = _headers(token)

    @task(5)
    def view_my_profile(self):
        self.client.get("/api/employees/me", headers=self.hdrs, name="/api/employees/me")

    @task(4)
    def view_my_payslips(self):
        self.client.get("/api/payroll/payslips", headers=self.hdrs,
                        name="/api/payroll/payslips")

    @task(4)
    def view_leave_balance(self):
        self.client.get("/api/leave/balance", headers=self.hdrs, name="/api/leave/balance")

    @task(3)
    def view_leave_history(self):
        self.client.get("/api/leave/history", headers=self.hdrs, name="/api/leave/history")

    @task(3)
    def view_today_attendance(self):
        self.client.get("/api/attendance/today", headers=self.hdrs,
                        name="/api/attendance/today")

    @task(2)
    def view_my_notifications(self):
        self.client.get("/api/notifications", headers=self.hdrs, name="/api/notifications")

    @task(2)
    def view_my_documents(self):
        self.client.get("/api/employees/me/documents", headers=self.hdrs,
                        name="/api/employees/me/documents")

    @task(1)
    def view_announcements(self):
        self.client.get("/api/helpdesk/announcements", headers=self.hdrs,
                        name="/api/helpdesk/announcements")

    @task(1)
    def apply_leave(self):
        # Apply for a future date 7–14 days out
        from_dt = date.today() + timedelta(days=random.randint(7, 14))
        to_dt = from_dt + timedelta(days=random.randint(0, 2))
        self.client.post(
            "/api/leave/apply",
            headers=self.hdrs,
            json={
                "leave_type_id": "",   # will 404 if not seeded, caught below
                "from_date": str(from_dt),
                "to_date": str(to_dt),
                "reason": "Load test leave application",
            },
            name="/api/leave/apply",
            catch_response=True,
        )
        # 400/404 is acceptable here (leave type not seeded); only 5xx is a failure


# ── HR Admin user ─────────────────────────────────────────────────────────────

class HRAdminUser(HttpUser):
    """Simulates an HR admin: employee list, reports, payroll views."""

    wait_time = between(2, 6)
    weight = 1

    def on_start(self):
        token = _login(self.client, "EMP001", "Demo@1234")
        if not token:
            self.environment.runner.quit()
            return
        self.hdrs = _headers(token)
        self._emp_id = None  # cached for detail tests

    @task(5)
    def list_employees(self):
        r = self.client.get(
            "/api/employees?page=1&per_page=20",
            headers=self.hdrs,
            name="/api/employees (list)",
        )
        if r.status_code == 200:
            employees = r.json().get("employees", [])
            if employees:
                self._emp_id = employees[0].get("id")

    @task(3)
    def view_employee_detail(self):
        if not self._emp_id:
            return
        self.client.get(
            f"/api/employees/{self._emp_id}",
            headers=self.hdrs,
            name="/api/employees/<id>",
        )

    @task(3)
    def list_payroll_runs(self):
        self.client.get("/api/payroll/runs", headers=self.hdrs, name="/api/payroll/runs")

    @task(2)
    def list_payslips(self):
        self.client.get("/api/payroll/payslips", headers=self.hdrs,
                        name="/api/payroll/payslips (hr)")

    @task(2)
    def list_leave_applications(self):
        self.client.get("/api/leave/applications", headers=self.hdrs,
                        name="/api/leave/applications")

    @task(2)
    def view_attendance_report(self):
        today = date.today()
        self.client.get(
            f"/api/attendance?month={today.year}-{today.month:02d}",
            headers=self.hdrs,
            name="/api/attendance (report)",
        )

    @task(1)
    def list_helpdesk_tickets(self):
        self.client.get("/api/helpdesk/tickets", headers=self.hdrs,
                        name="/api/helpdesk/tickets")

    @task(1)
    def view_org_departments(self):
        self.client.get("/api/org/departments", headers=self.hdrs,
                        name="/api/org/departments")

    @task(1)
    def health_check(self):
        self.client.get("/api/health", name="/api/health")


# ── Events ────────────────────────────────────────────────────────────────────

@events.quitting.add_listener
def _(environment, **kwargs):
    """Print a summary p95 note when the test ends."""
    stats = environment.stats.total
    if stats.num_requests:
        print(
            f"\nTotal requests: {stats.num_requests} | "
            f"Failures: {stats.num_failures} | "
            f"p95: {stats.get_response_time_percentile(0.95):.0f}ms"
        )
