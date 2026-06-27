"""
Enterprise Payroll Computation Engine
Supports: India (PF/ESI/PT/LWF/TDS), UAE (Gratuity/WPS), US (FICA/Federal)

IMPORTANT: These computations reflect statutory rules as of FY 2025-26.
Must be reviewed by a qualified CA (India), Labour Consultant (UAE),
or CPA (US) before processing live payroll.
"""
from decimal import Decimal, ROUND_HALF_UP


def _round(val) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class IndiaPayrollEngine:
    # ── Constants (FY 2025-26) ────────────────────────────────────────────────
    PF_EMPLOYEE_PCT = Decimal("0.12")
    PF_EMPLOYER_EPS_PCT = Decimal("0.0833")
    PF_EMPLOYER_EPF_PCT = Decimal("0.0367")
    PF_WAGE_CEILING = Decimal("15000")
    ESI_EMPLOYEE_PCT = Decimal("0.0075")
    ESI_EMPLOYER_PCT = Decimal("0.0325")
    ESI_WAGE_CEILING = Decimal("21000")
    EDLI_EMPLOYER_PCT = Decimal("0.005")
    PF_ADMIN_PCT = Decimal("0.005")

    PT_SLABS = {
        "MH": [(10000, 0), (999999, 200)],
        "KA": [(25000, 0), (999999, 200)],
        "TN": [(21000, 0), (999999, 208)],
        "WB": [(10000, 0), (15000, 110), (25000, 130), (40000, 150), (999999, 200)],
        "DEFAULT": [(15000, 0), (999999, 200)],
    }

    TDS_NEW_REGIME_SLABS = [
        (400000, 0.0),
        (800000, 0.05),
        (1200000, 0.10),
        (1600000, 0.15),
        (2000000, 0.20),
        (2400000, 0.25),
        (float("inf"), 0.30),
    ]

    def __init__(self, employee, salary, paid_days, total_days, year, month):
        self.employee = employee
        self.salary = salary
        self.paid_days = Decimal(str(paid_days))
        self.total_days = Decimal(str(total_days))
        self.year = year
        self.month = month
        self.country_state = getattr(salary, "india_professional_tax_state", "DEFAULT") or "DEFAULT"
        self.tax_regime = getattr(salary, "india_tax_regime", "new") or "new"

    def calculate(self) -> dict:
        ctc_monthly = _round(self.salary.ctc_monthly)
        ratio = self.paid_days / self.total_days if self.total_days > 0 else Decimal("1")

        basic = _round((self.salary.india_basic or ctc_monthly * Decimal("0.4")) * ratio)
        hra = _round((self.salary.india_hra or ctc_monthly * Decimal("0.2")) * ratio)

        components = dict(self.salary.components or {})
        earnings = {"Basic": float(basic), "HRA": float(hra)}
        for code, val in components.items():
            earnings[code] = float(_round(Decimal(str(val)) * ratio))

        gross = _round(sum(Decimal(str(v)) for v in earnings.values()))

        # PF
        pf_basic = min(basic, self.PF_WAGE_CEILING)
        pf_employee = _round(pf_basic * self.PF_EMPLOYEE_PCT)
        pf_employer_eps = _round(pf_basic * self.PF_EMPLOYER_EPS_PCT)
        pf_employer_epf = _round(pf_basic * self.PF_EMPLOYER_EPF_PCT)
        pf_employer = pf_employer_eps + pf_employer_epf
        edli = _round(pf_basic * self.EDLI_EMPLOYER_PCT)
        pf_admin = _round(pf_basic * self.PF_ADMIN_PCT)

        # ESI
        esi_employee = Decimal("0")
        esi_employer = Decimal("0")
        if gross <= self.ESI_WAGE_CEILING:
            esi_employee = _round(gross * self.ESI_EMPLOYEE_PCT)
            esi_employer = _round(gross * self.ESI_EMPLOYER_PCT)

        # Professional Tax
        pt = self._compute_pt(gross)

        # TDS (monthly estimate)
        annual_gross = gross * 12
        standard_deduction = Decimal("75000")
        taxable_income = max(Decimal("0"), annual_gross - standard_deduction)
        annual_tds = self._compute_tds(taxable_income)
        tds_monthly = _round(annual_tds / 12)

        total_deductions = pf_employee + esi_employee + pt + tds_monthly
        net = gross - total_deductions

        return {
            "earnings": earnings,
            "deductions": {
                "PF (Employee)": float(pf_employee),
                "ESI (Employee)": float(esi_employee),
                "Professional Tax": float(pt),
                "TDS": float(tds_monthly),
            },
            "employer_contributions": {
                "PF (Employer)": float(pf_employer),
                "ESI (Employer)": float(esi_employer),
                "EDLI": float(edli),
                "PF Admin": float(pf_admin),
            },
            "gross": float(gross),
            "total_deductions": float(total_deductions),
            "net": float(net),
            "statutory": {
                "india_pf_employee": float(pf_employee),
                "india_pf_employer": float(pf_employer),
                "india_esi_employee": float(esi_employee),
                "india_esi_employer": float(esi_employer),
                "india_pt": float(pt),
                "india_tds": float(tds_monthly),
            },
        }

    def _compute_pt(self, monthly_gross: Decimal) -> Decimal:
        slabs = self.PT_SLABS.get(self.country_state, self.PT_SLABS["DEFAULT"])
        prev = Decimal("0")
        for ceiling, amount in slabs:
            if monthly_gross > prev and monthly_gross <= Decimal(str(ceiling)):
                return Decimal(str(amount))
            prev = Decimal(str(ceiling))
        return Decimal("200")

    def _compute_tds(self, taxable_income: Decimal) -> Decimal:
        tax = Decimal("0")
        prev_limit = Decimal("0")
        for limit, rate in self.TDS_NEW_REGIME_SLABS:
            if taxable_income <= Decimal(str(prev_limit)):
                break
            slab_income = min(taxable_income, Decimal(str(limit))) - prev_limit
            tax += _round(slab_income * Decimal(str(rate)))
            if taxable_income <= Decimal(str(limit)):
                break
            prev_limit = Decimal(str(limit))
        # 87A rebate: if income <= 7L, tax = 0
        if taxable_income <= Decimal("700000"):
            tax = Decimal("0")
        # 4% health & education cess
        cess = _round(tax * Decimal("0.04"))
        return tax + cess


class UAEPayrollEngine:
    def __init__(self, employee, salary, paid_days, total_days, year, month):
        self.employee = employee
        self.salary = salary
        self.paid_days = Decimal(str(paid_days))
        self.total_days = Decimal(str(total_days))

    def calculate(self) -> dict:
        ratio = self.paid_days / self.total_days if self.total_days > 0 else Decimal("1")
        basic = _round((self.salary.uae_basic or Decimal("0")) * ratio)
        housing = _round((self.salary.uae_housing or Decimal("0")) * ratio)
        transport = _round((self.salary.uae_transport or Decimal("0")) * ratio)
        other = _round((self.salary.uae_other_allowances or Decimal("0")) * ratio)
        gross = basic + housing + transport + other

        # UAE has no income tax; only GPSSA for UAE nationals (not computed here)
        return {
            "earnings": {
                "Basic": float(basic),
                "Housing Allowance": float(housing),
                "Transport Allowance": float(transport),
                "Other Allowances": float(other),
            },
            "deductions": {},
            "employer_contributions": {},
            "gross": float(gross),
            "total_deductions": 0.0,
            "net": float(gross),
            "statutory": {},
        }

    @staticmethod
    def compute_gratuity(basic_monthly: float, service_years: float, exit_type: str) -> float:
        daily_wage = Decimal(str(basic_monthly)) / 30
        days = Decimal("0")
        years = Decimal(str(service_years))
        if years < Decimal("1"):
            return 0.0
        if years <= Decimal("5"):
            days = years * 21
        else:
            days = (Decimal("5") * 21) + ((years - 5) * 30)

        if exit_type == "resignation":
            if years < 3:
                days *= Decimal("0.33")
            elif years < 5:
                days *= Decimal("0.67")

        return float(_round(daily_wage * days))


class USPayrollEngine:
    SS_RATE = Decimal("0.062")
    SS_WAGE_BASE = Decimal("168600")
    MEDICARE_RATE = Decimal("0.0145")
    MEDICARE_ADDITIONAL_RATE = Decimal("0.009")
    MEDICARE_ADDITIONAL_THRESHOLD = Decimal("200000")

    FEDERAL_SINGLE_2025 = [
        (11925, 0.10),
        (47150, 0.12),
        (100525, 0.22),
        (191950, 0.24),
        (243725, 0.32),
        (609350, 0.35),
        (float("inf"), 0.37),
    ]

    def __init__(self, employee, salary, paid_days, total_days, year, month):
        self.employee = employee
        self.salary = salary
        self.paid_days = Decimal(str(paid_days))
        self.total_days = Decimal(str(total_days))

    def calculate(self) -> dict:
        ratio = self.paid_days / self.total_days if self.total_days > 0 else Decimal("1")
        ctc_monthly = _round(self.salary.ctc_monthly * ratio)
        gross = ctc_monthly

        # Social Security
        ytd_gross = Decimal("0")
        ss = Decimal("0")
        if ytd_gross < self.SS_WAGE_BASE:
            ss_eligible = min(gross, self.SS_WAGE_BASE - ytd_gross)
            ss = _round(ss_eligible * self.SS_RATE)

        # Medicare
        medicare = _round(gross * self.MEDICARE_RATE)
        annual_gross = gross * 12
        if annual_gross > self.MEDICARE_ADDITIONAL_THRESHOLD:
            medicare += _round((annual_gross - self.MEDICARE_ADDITIONAL_THRESHOLD) / 12 * self.MEDICARE_ADDITIONAL_RATE)

        # Federal withholding (simplified — actual W4 required)
        annual = gross * 12
        federal_annual = self._compute_federal(annual)
        federal_monthly = _round(federal_annual / 12)

        total_deductions = ss + medicare + federal_monthly
        net = gross - total_deductions

        return {
            "earnings": {"Gross Pay": float(gross)},
            "deductions": {
                "Social Security": float(ss),
                "Medicare": float(medicare),
                "Federal Income Tax": float(federal_monthly),
            },
            "employer_contributions": {
                "Social Security (Employer)": float(ss),
                "Medicare (Employer)": float(_round(gross * self.MEDICARE_RATE)),
            },
            "gross": float(gross),
            "total_deductions": float(total_deductions),
            "net": float(net),
            "statutory": {
                "us_social_security": float(ss),
                "us_medicare": float(medicare),
                "us_federal_tax": float(federal_monthly),
            },
        }

    def _compute_federal(self, annual_income: Decimal) -> Decimal:
        tax = Decimal("0")
        prev = Decimal("0")
        for limit, rate in self.FEDERAL_SINGLE_2025:
            if annual_income <= prev:
                break
            slab = min(annual_income, Decimal(str(limit))) - prev
            tax += _round(slab * Decimal(str(rate)))
            if annual_income <= Decimal(str(limit)):
                break
            prev = Decimal(str(limit))
        return tax
