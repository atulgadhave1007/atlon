"""
Payroll integration tests.
Covers: engine math (PF/ESI/PT/TDS) for India, UAE, US;
        full API run flow with real DB; schema validation.
"""
import uuid
import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ── Module-wide email suppression ─────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _no_email():
    """Prevent queue_email from touching Celery/Redis/SMTP during tests."""
    with patch("app.services.email_service.queue_email", return_value=None):
        yield


# ── Helper factories (no DB / HTTP required) ──────────────────────────────────

def _india_engine(basic=20000, hra=10000, components=None, state="DEFAULT",
                  regime="new", paid=26, total=26):
    from app.services.payroll_engine import IndiaPayrollEngine
    salary = MagicMock()
    salary.ctc_monthly = Decimal(str(basic + hra + sum((components or {}).values())))
    salary.india_basic = Decimal(str(basic))
    salary.india_hra = Decimal(str(hra))
    salary.components = components or {}
    salary.india_professional_tax_state = state
    salary.india_tax_regime = regime
    return IndiaPayrollEngine(MagicMock(), salary, paid, total, 2024, 1)


def _uae_engine(basic=10000, housing=5000, transport=2000, other=1000,
                paid=30, total=30):
    from app.services.payroll_engine import UAEPayrollEngine
    salary = MagicMock()
    salary.uae_basic = Decimal(str(basic))
    salary.uae_housing = Decimal(str(housing))
    salary.uae_transport = Decimal(str(transport))
    salary.uae_other_allowances = Decimal(str(other))
    return UAEPayrollEngine(MagicMock(), salary, paid, total, 2024, 1)


def _us_engine(ctc_monthly=10000, paid=31, total=31):
    from app.services.payroll_engine import USPayrollEngine
    salary = MagicMock()
    salary.ctc_monthly = Decimal(str(ctc_monthly))
    salary.us_federal_filing_status = "single"
    salary.us_w4_allowances = 0
    salary.us_additional_withholding = Decimal("0")
    return USPayrollEngine(MagicMock(), salary, paid, total, 2024, 1)


# ── India Payroll Engine ──────────────────────────────────────────────────────

class TestIndiaPayrollEngine:

    def test_gross_is_sum_of_earnings(self):
        result = _india_engine(basic=20000, hra=10000, components={"TA": 5000}).calculate()
        assert result["gross"] == pytest.approx(35000.0)

    def test_pf_capped_at_15k_wage_ceiling(self):
        # basic 50000 > 15000 ceiling → PF on 15000 × 12% = 1800
        result = _india_engine(basic=50000, hra=20000, components={"TA": 10000}).calculate()
        assert result["deductions"]["PF (Employee)"] == pytest.approx(1800.0)
        assert result["employer_contributions"]["PF (Employer)"] == pytest.approx(1800.0)

    def test_pf_uncapped_when_basic_below_ceiling(self):
        # basic 12000 < 15000 → PF on 12000 × 12% = 1440
        result = _india_engine(basic=12000, hra=5000, components={"TA": 2000}).calculate()
        assert result["deductions"]["PF (Employee)"] == pytest.approx(1440.0)

    def test_esi_applied_when_gross_at_or_below_21k(self):
        # gross = 12000 + 5000 + 2000 = 19000 ≤ 21000
        result = _india_engine(basic=12000, hra=5000, components={"TA": 2000}).calculate()
        assert result["gross"] <= 21000
        # ESI employee = 19000 × 0.75% = 142.50
        assert result["deductions"]["ESI (Employee)"] == pytest.approx(142.50)
        # ESI employer = 19000 × 3.25% = 617.50
        assert result["employer_contributions"]["ESI (Employer)"] == pytest.approx(617.50)

    def test_esi_exempt_when_gross_above_21k(self):
        # gross = 20000 + 10000 + 10000 + 10000 = 50000 > 21000
        result = _india_engine(basic=20000, hra=10000,
                                components={"TA": 10000, "Other": 10000}).calculate()
        assert result["gross"] > 21000
        assert result["deductions"]["ESI (Employee)"] == pytest.approx(0.0)

    def test_87a_rebate_zero_tds_when_taxable_below_7l(self):
        # CTC 50000/mo → annual gross 600K, taxable 525K < 700K → 87A rebate → TDS = 0
        result = _india_engine(basic=20000, hra=10000,
                                components={"TA": 10000, "Other": 10000}).calculate()
        assert result["deductions"]["TDS"] == pytest.approx(0.0)
        assert result["statutory"]["india_tds"] == pytest.approx(0.0)

    def test_tds_charged_when_taxable_above_7l(self):
        # gross 125000/mo → taxable 1425000 > 700000 → TDS applied
        result = _india_engine(basic=50000, hra=25000,
                                components={"TA": 25000, "Other": 25000}).calculate()
        assert result["deductions"]["TDS"] > 0

    def test_tds_exact_amount_new_regime(self):
        # taxable = (125000 × 12) − 75000 = 1 425 000
        # slabs: 400K@0%=0, 400K@5%=20000, 400K@10%=40000, 225K@15%=33750 = 93750
        # cess 4% = 3750 → annual 97500 → monthly 8125.00
        result = _india_engine(basic=50000, hra=25000,
                                components={"TA": 25000, "Other": 25000}).calculate()
        assert result["statutory"]["india_tds"] == pytest.approx(8125.0)

    def test_pt_default_slab_zero_below_15k(self):
        # DEFAULT: gross ≤ 15000 → PT = 0
        result = _india_engine(basic=8000, hra=4000, components={"TA": 1000}).calculate()
        assert result["deductions"]["Professional Tax"] == pytest.approx(0.0)

    def test_pt_default_slab_200_above_15k(self):
        # DEFAULT: gross > 15000 → PT = 200
        result = _india_engine(basic=10000, hra=5000, components={"TA": 5000}).calculate()
        assert result["deductions"]["Professional Tax"] == pytest.approx(200.0)

    def test_pt_karnataka_zero_below_25k(self):
        # KA: gross ≤ 25000 → PT = 0
        result = _india_engine(basic=12000, hra=5000, components={"TA": 2000},
                                state="KA").calculate()
        assert result["deductions"]["Professional Tax"] == pytest.approx(0.0)

    def test_pt_maharashtra_200_above_10k(self):
        # MH: gross > 10000 → PT = 200
        result = _india_engine(basic=10000, hra=5000, components={"TA": 1000},
                                state="MH").calculate()
        assert result["deductions"]["Professional Tax"] == pytest.approx(200.0)

    def test_net_equals_gross_minus_total_deductions(self):
        result = _india_engine().calculate()
        assert result["net"] == pytest.approx(result["gross"] - result["total_deductions"])

    def test_prorated_salary_lower_than_full(self):
        full = _india_engine(paid=26, total=26).calculate()
        partial = _india_engine(paid=20, total=26).calculate()
        assert partial["gross"] < full["gross"]
        assert partial["gross"] == pytest.approx(full["gross"] * 20 / 26, rel=0.01)

    def test_zero_paid_days_yields_zero_gross(self):
        result = _india_engine(paid=0, total=26).calculate()
        assert result["gross"] == pytest.approx(0.0)

    def test_earnings_dict_has_basic_and_hra(self):
        result = _india_engine().calculate()
        assert "Basic" in result["earnings"]
        assert "HRA" in result["earnings"]

    def test_employer_contributions_present(self):
        result = _india_engine().calculate()
        assert "PF (Employer)" in result["employer_contributions"]
        assert "ESI (Employer)" in result["employer_contributions"]

    def test_components_included_in_gross(self):
        result = _india_engine(basic=20000, hra=10000,
                                components={"Special Allowance": 5000}).calculate()
        assert "Special Allowance" in result["earnings"]
        assert result["gross"] == pytest.approx(35000.0)


# ── UAE Payroll Engine ────────────────────────────────────────────────────────

class TestUAEPayrollEngine:

    def test_gross_equals_sum_of_all_allowances(self):
        result = _uae_engine(basic=10000, housing=5000, transport=2000, other=1000).calculate()
        assert result["gross"] == pytest.approx(18000.0)

    def test_no_deductions_in_uae(self):
        result = _uae_engine().calculate()
        assert result["total_deductions"] == pytest.approx(0.0)
        assert result["deductions"] == {}

    def test_net_equals_gross(self):
        result = _uae_engine().calculate()
        assert result["net"] == pytest.approx(result["gross"])

    def test_earnings_breakdown_keys(self):
        result = _uae_engine().calculate()
        assert "Basic" in result["earnings"]
        assert "Housing Allowance" in result["earnings"]
        assert "Transport Allowance" in result["earnings"]
        assert "Other Allowances" in result["earnings"]

    def test_prorated_uae_salary(self):
        full = _uae_engine(paid=30, total=30).calculate()
        partial = _uae_engine(paid=20, total=30).calculate()
        assert partial["gross"] < full["gross"]
        assert partial["gross"] == pytest.approx(full["gross"] * 20 / 30, rel=0.01)

    def test_gratuity_5yr_termination(self):
        from app.services.payroll_engine import UAEPayrollEngine
        # 5yr × 21 days = 105 days, daily = 5000/30 = 166.67 → 17500
        gratuity = UAEPayrollEngine.compute_gratuity(5000.0, 5.0, "termination")
        assert gratuity == pytest.approx(17500.0, rel=0.01)

    def test_gratuity_over_5yr_uses_30_days_per_extra_year(self):
        from app.services.payroll_engine import UAEPayrollEngine
        # 6yr: (5×21 + 1×30) = 135 days → 22500
        g6 = UAEPayrollEngine.compute_gratuity(5000.0, 6.0, "termination")
        g5 = UAEPayrollEngine.compute_gratuity(5000.0, 5.0, "termination")
        assert g6 > g5
        assert g6 == pytest.approx(22500.0, rel=0.01)

    def test_gratuity_resignation_under_3yr_is_33pct(self):
        from app.services.payroll_engine import UAEPayrollEngine
        resign = UAEPayrollEngine.compute_gratuity(5000.0, 2.0, "resignation")
        terminate = UAEPayrollEngine.compute_gratuity(5000.0, 2.0, "termination")
        assert resign == pytest.approx(terminate * 0.33, rel=0.01)

    def test_gratuity_zero_under_1yr(self):
        from app.services.payroll_engine import UAEPayrollEngine
        assert UAEPayrollEngine.compute_gratuity(5000.0, 0.5, "termination") == 0.0


# ── US Payroll Engine ─────────────────────────────────────────────────────────

class TestUSPayrollEngine:

    def test_social_security_is_6_2_pct(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        assert result["deductions"]["Social Security"] == pytest.approx(10000 * 0.062)

    def test_medicare_is_1_45_pct(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        assert result["deductions"]["Medicare"] == pytest.approx(10000 * 0.0145)

    def test_federal_withholding_applied(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        assert result["deductions"]["Federal Income Tax"] > 0

    def test_federal_withholding_exact_single_2025(self):
        # Annual = 120 000; slabs: 11925@10% + 35225@12% + 53375@22% + 19475@24%
        # = 1192.50 + 4227 + 11742.50 + 4674 = 21836 → monthly = 1819.67
        result = _us_engine(ctc_monthly=10000).calculate()
        assert result["deductions"]["Federal Income Tax"] == pytest.approx(1819.67, abs=0.01)

    def test_net_positive(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        assert result["net"] > 0

    def test_net_equals_gross_minus_deductions(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        assert result["net"] == pytest.approx(result["gross"] - result["total_deductions"])

    def test_employer_ss_matches_employee_ss(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        assert (result["employer_contributions"]["Social Security (Employer)"]
                == result["deductions"]["Social Security"])

    def test_statutory_keys_present(self):
        result = _us_engine(ctc_monthly=10000).calculate()
        for key in ("us_social_security", "us_medicare", "us_federal_tax"):
            assert key in result["statutory"]


# ── Schema Validation (pure Python, no HTTP) ──────────────────────────────────

class TestPayrollRunSchema:

    def test_future_period_rejected(self):
        from app.schemas.payroll import PayrollRunSchema
        from marshmallow import ValidationError
        import datetime as dt
        now = dt.datetime.now()
        with pytest.raises(ValidationError) as exc:
            PayrollRunSchema().load({"year": now.year + 1, "month": 1})
        assert exc.value.messages  # some error present

    def test_month_zero_rejected(self):
        from app.schemas.payroll import PayrollRunSchema
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            PayrollRunSchema().load({"year": 2024, "month": 0})

    def test_month_13_rejected(self):
        from app.schemas.payroll import PayrollRunSchema
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            PayrollRunSchema().load({"year": 2024, "month": 13})

    def test_current_period_accepted(self):
        import datetime as dt
        now = dt.datetime.now()
        from app.schemas.payroll import PayrollRunSchema
        result = PayrollRunSchema().load({"year": now.year, "month": now.month})
        assert result["year"] == now.year
        assert result["month"] == now.month

    def test_past_period_accepted(self):
        from app.schemas.payroll import PayrollRunSchema
        result = PayrollRunSchema().load({"year": 2024, "month": 3})
        assert result["year"] == 2024
        assert result["month"] == 3

    def test_employee_ids_optional(self):
        from app.schemas.payroll import PayrollRunSchema
        result = PayrollRunSchema().load({"year": 2024, "month": 3})
        assert result.get("employee_ids") is None

    def test_employee_ids_list_accepted(self):
        from app.schemas.payroll import PayrollRunSchema
        result = PayrollRunSchema().load({
            "year": 2024, "month": 3,
            "employee_ids": ["abc", "def"],
        })
        assert result["employee_ids"] == ["abc", "def"]


# ── API Integration Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def payint_employee(db, seeded):
    """India employee with a current salary — created once per module."""
    from app.models import Employee, EmployeeStatus, Role, EmployeeSalary

    emp = Employee.query.filter_by(
        work_email="payint@testco.test", is_deleted=False
    ).first()
    if emp:
        return emp

    emp = Employee(
        tenant_id=str(seeded["tenant"].id),
        employee_number="PAYINT001",
        first_name="Pay",
        last_name="Integration",
        work_email="payint@testco.test",
        password_hash=Employee.hash_password("Test@1234!"),
        date_of_joining=date(2022, 1, 1),
        status=EmployeeStatus.ACTIVE,
        role=Role.EMPLOYEE,
        is_active=True,
    )
    db.session.add(emp)
    db.session.flush()

    salary = EmployeeSalary(
        tenant_id=str(seeded["tenant"].id),
        employee_id=str(emp.id),
        effective_from=date(2022, 1, 1),
        effective_to=None,
        ctc_annual=Decimal("600000"),
        ctc_monthly=Decimal("50000"),
        currency="INR",
        india_basic=Decimal("20000"),
        india_hra=Decimal("10000"),
        india_professional_tax_state="DEFAULT",
        india_tax_regime="new",
        components={"TA": 10000, "Other Allowance": 10000},
    )
    db.session.add(salary)
    db.session.commit()
    return emp


@pytest.fixture(scope="module")
def march_2023_attendance(db, seeded, payint_employee):
    """31 PRESENT records for March 2023 — idempotent."""
    from app.models import Attendance, AttendanceStatus
    tid = str(seeded["tenant"].id)
    eid = str(payint_employee.id)

    existing_count = Attendance.query.filter_by(
        tenant_id=tid, employee_id=eid, is_deleted=False
    ).filter(
        db.extract("year", Attendance.date) == 2023,
        db.extract("month", Attendance.date) == 3,
    ).count()

    if existing_count == 31:
        return

    for day in range(1, 32):
        try:
            d = date(2023, 3, day)
        except ValueError:
            break
        rec = Attendance(
            id=uuid.uuid4(),
            tenant_id=tid,
            employee_id=eid,
            date=d,
            status=AttendanceStatus.PRESENT,
            check_in=datetime(2023, 3, day, 9, 0, tzinfo=timezone.utc),
        )
        db.session.add(rec)
    db.session.commit()


@pytest.fixture(scope="module")
def run_march_2023(client, auth_headers, payint_employee, march_2023_attendance):
    """Run payroll for March 2023 once; return the response JSON."""
    r = client.post(
        "/api/payroll/run",
        headers=auth_headers,
        json={"year": 2023, "month": 3},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


@pytest.fixture(scope="module")
def payslip_march_2023(db, seeded, payint_employee, run_march_2023):
    """Payslip for payint_employee in March 2023."""
    from app.models import Payslip
    slip = Payslip.query.filter_by(
        tenant_id=str(seeded["tenant"].id),
        employee_id=str(payint_employee.id),
        year=2023, month=3, is_deleted=False,
    ).first()
    assert slip is not None, "Payslip for March 2023 not found after payroll run"
    return slip


# ── API Integration Tests ─────────────────────────────────────────────────────

class TestPayrollAPIRun:

    def test_run_returns_run_id(self, run_march_2023):
        assert "run_id" in run_march_2023
        assert run_march_2023["run_id"]

    def test_run_processes_at_least_one_employee(self, run_march_2023):
        assert run_march_2023["employee_count"] >= 1

    def test_run_total_gross_positive(self, run_march_2023):
        assert run_march_2023["total_gross"] > 0

    def test_run_total_net_positive(self, run_march_2023):
        assert run_march_2023["total_net"] > 0

    def test_run_net_less_than_gross(self, run_march_2023):
        assert run_march_2023["total_net"] < run_march_2023["total_gross"]

    def test_run_message_present(self, run_march_2023):
        assert run_march_2023.get("message") == "Payroll processed"


class TestPayslipStatutoryAmounts:
    """Verify payslip statutory fields produced by the full run → DB path."""

    def test_gross_equals_full_month_salary(self, payslip_march_2023):
        # basic 20K + hra 10K + TA 10K + Other 10K = 50K (31/31 paid days)
        assert float(payslip_march_2023.gross_earnings) == pytest.approx(50000.0)

    def test_pf_employee_capped_at_1800(self, payslip_march_2023):
        # basic 20K > 15K ceiling → PF on 15K × 12% = 1800
        assert float(payslip_march_2023.india_pf_employee) == pytest.approx(1800.0)

    def test_esi_zero_because_gross_above_threshold(self, payslip_march_2023):
        # gross 50K > 21K → ESI = 0
        assert float(payslip_march_2023.india_esi_employee) == pytest.approx(0.0)

    def test_pt_200_for_default_state(self, payslip_march_2023):
        assert float(payslip_march_2023.india_pt) == pytest.approx(200.0)

    def test_tds_zero_87a_rebate(self, payslip_march_2023):
        # annual taxable 525K < 700K → 87A rebate → TDS = 0
        assert float(payslip_march_2023.india_tds) == pytest.approx(0.0)

    def test_net_pay_correct(self, payslip_march_2023):
        # 50000 − 1800 (PF) − 0 (ESI) − 200 (PT) − 0 (TDS) = 48000
        assert float(payslip_march_2023.net_pay) == pytest.approx(48000.0)

    def test_paid_days_equals_31(self, payslip_march_2023):
        assert float(payslip_march_2023.paid_days) == pytest.approx(31.0)


class TestPayrollAPIValidation:

    def test_future_period_returns_422(self, client, auth_headers):
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"year": 2099, "month": 1},
        )
        assert r.status_code == 422
        assert "errors" in r.get_json()

    def test_invalid_month_13_returns_422(self, client, auth_headers):
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"year": 2024, "month": 13},
        )
        assert r.status_code == 422

    def test_invalid_month_0_returns_422(self, client, auth_headers):
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"year": 2024, "month": 0},
        )
        assert r.status_code == 422

    def test_missing_year_returns_422(self, client, auth_headers):
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"month": 3},
        )
        assert r.status_code == 422

    def test_missing_month_returns_422(self, client, auth_headers):
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"year": 2024},
        )
        assert r.status_code == 422

    def test_unauthenticated_run_returns_401(self, client):
        r = client.post(
            "/api/payroll/run",
            json={"year": 2024, "month": 3},
        )
        assert r.status_code == 401

    def test_rerun_non_locked_period_is_200(self, client, auth_headers, run_march_2023):
        # Re-running a non-locked period replaces payslips — should succeed
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"year": 2023, "month": 3},
        )
        assert r.status_code == 200

    def test_list_runs_includes_march_2023(self, client, auth_headers, run_march_2023):
        r = client.get("/api/payroll/runs", headers=auth_headers)
        assert r.status_code == 200
        run_ids = [run["id"] for run in r.get_json()["runs"]]
        assert run_march_2023["run_id"] in run_ids

    def test_list_payslips_for_march_2023(self, client, auth_headers, run_march_2023):
        r = client.get("/api/payroll/payslips?month=2023-03", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.get_json()["payslips"]) >= 1


class TestPayrollLock:
    """Lock tests must run after the main payroll run tests."""

    def test_lock_run_succeeds(self, client, auth_headers, run_march_2023):
        run_id = run_march_2023["run_id"]
        r = client.post(f"/api/payroll/runs/{run_id}/lock", headers=auth_headers)
        assert r.status_code == 200

    def test_rerun_locked_period_returns_409(self, client, auth_headers):
        r = client.post(
            "/api/payroll/run",
            headers=auth_headers,
            json={"year": 2023, "month": 3},
        )
        assert r.status_code == 409
