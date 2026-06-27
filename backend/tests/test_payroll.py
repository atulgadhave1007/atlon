import pytest
from decimal import Decimal
from unittest.mock import MagicMock


def _make_india_engine(basic=30000, hra=15000, paid=26, total=26, lop=0):
    from app.services.payroll_engine import IndiaPayrollEngine
    employee = MagicMock()
    salary = MagicMock()
    salary.ctc_monthly = Decimal(str((basic + hra + 5000)))
    salary.ctc_annual = salary.ctc_monthly * 12
    salary.india_basic = Decimal(str(basic))
    salary.india_hra = Decimal(str(hra))
    salary.components = {'Special Allowance': 5000}
    salary.india_professional_tax_state = 'DEFAULT'
    salary.india_tax_regime = 'new'
    return IndiaPayrollEngine(employee, salary, paid - lop, total, 2025, 6)


class TestPayrollEngine:
    def test_india_payroll_basic(self):
        engine = _make_india_engine()
        result = engine.calculate()
        assert result['gross'] > 0
        assert result['net'] > 0
        assert result['net'] < result['gross']
        assert any('PF' in k for k in result['deductions'])
        assert any('PF' in k for k in result['employer_contributions'])

    def test_india_payroll_lop(self):
        full = _make_india_engine(lop=0).calculate()
        lop = _make_india_engine(lop=3).calculate()
        assert lop['net'] < full['net']

    def test_india_esi_threshold(self):
        low_engine = _make_india_engine(basic=10000, hra=5000)
        result = low_engine.calculate()
        assert any('ESI' in k for k in result['deductions'])

    def test_uae_payroll(self):
        from app.services.payroll_engine import UAEPayrollEngine
        employee = MagicMock()
        salary = MagicMock()
        salary.ctc_monthly = Decimal('7500')
        salary.ctc_annual = Decimal('90000')
        salary.uae_basic = Decimal('5000')
        salary.uae_housing = Decimal('2000')
        salary.uae_transport = Decimal('500')
        salary.uae_other_allowances = Decimal('0')
        salary.components = {}
        engine = UAEPayrollEngine(employee, salary, 22, 22, 2025, 6)
        result = engine.calculate()
        assert result['gross'] > 0
        assert result['net'] > 0

    def test_us_payroll(self):
        from app.services.payroll_engine import USPayrollEngine
        employee = MagicMock()
        salary = MagicMock()
        salary.ctc_monthly = Decimal('6000')
        salary.ctc_annual = Decimal('72000')
        salary.components = {}
        salary.us_federal_filing_status = 'single'
        salary.us_w4_allowances = 1
        salary.us_additional_withholding = Decimal('0')
        engine = USPayrollEngine(employee, salary, 21, 21, 2025, 6)
        result = engine.calculate()
        assert result['gross'] > 0
        assert any('Social Security' in k or 'Medicare' in k for k in result['deductions'])
        assert result['net'] > 0

    def test_uae_gratuity_2yr(self):
        from app.services.payroll_engine import UAEPayrollEngine
        gratuity = UAEPayrollEngine.compute_gratuity(5000.0, 2.0, 'resignation')
        assert gratuity > 0

    def test_uae_gratuity_more_years(self):
        from app.services.payroll_engine import UAEPayrollEngine
        g2 = UAEPayrollEngine.compute_gratuity(5000.0, 2.0, 'resignation')
        g5 = UAEPayrollEngine.compute_gratuity(5000.0, 5.0, 'resignation')
        assert g5 > g2


class TestPayrollAPI:
    def test_payroll_run(self, client, auth_headers):
        from datetime import date
        today = date.today()
        r = client.post('/api/payroll/run', headers=auth_headers, json={
            'year': today.year,
            'month': today.month
        })
        assert r.status_code in (200, 201, 400)

    def test_list_payslips(self, client, auth_headers):
        r = client.get('/api/payroll/payslips', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'payslips' in data

    def test_list_runs(self, client, auth_headers):
        r = client.get('/api/payroll/runs', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'runs' in data
