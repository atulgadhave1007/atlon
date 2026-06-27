import csv
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from io import StringIO


_EPS_WAGE_CAP = Decimal("15000")
_EPS_RATE = Decimal("0.0833")
_ESI_THRESHOLD = Decimal("21000")


def generate_pf_ecr(payslips: list, employees: dict) -> str:
    """
    EPFO ECR 2.0 CSV.

    employees: {str(employee_id): Employee ORM object}
    """
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow([
        "UAN", "MEMBER_NAME", "GROSS_WAGES", "EPF_WAGES", "EPS_WAGES",
        "EDLI_WAGES", "EPF_CONTRIBUTION_REMITTED", "EPS_CONTRIBUTION_REMITTED",
        "EPF_EPS_DIFF_REMITTED", "LPP_ARREARS_EPF", "LPP_ARREARS_EPS",
        "NCP_DAYS", "REFUND_OF_ADVANCES",
    ])
    for slip in payslips:
        emp = employees.get(str(slip.employee_id))
        if not emp:
            continue

        gross = Decimal(str(slip.gross_earnings or 0))
        pf_contribution = Decimal(str(slip.india_pf_employee or 0))

        # Back-calculate EPF wages from employee share (12 %)
        epf_wages = (pf_contribution / Decimal("0.12")).quantize(Decimal("0.01")) if pf_contribution else Decimal("0")
        eps_wages = min(epf_wages, _EPS_WAGE_CAP)
        eps_contribution = (eps_wages * _EPS_RATE).quantize(Decimal("0.01"))
        epf_eps_diff = max(Decimal("0"), pf_contribution - eps_contribution)
        ncp_days = int(slip.lop_days or 0)

        w.writerow([
            emp.uan or "",
            emp.full_name,
            f"{gross:.2f}",
            f"{epf_wages:.2f}",
            f"{eps_wages:.2f}",
            f"{eps_wages:.2f}",       # EDLI wages = EPS wages
            f"{pf_contribution:.2f}",
            f"{eps_contribution:.2f}",
            f"{epf_eps_diff:.2f}",
            "0", "0",
            ncp_days,
            "0",
        ])
    return buf.getvalue()


def generate_esi_return(payslips: list, employees: dict) -> str:
    """
    ESI monthly return CSV.
    Only includes employees earning ≤ ₹21,000 gross (ESI eligibility).
    """
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow([
        "ESI_NUMBER", "EMPLOYEE_NAME", "GROSS_WAGES",
        "ESI_WAGES", "EMPLOYEE_CONTRIBUTION", "EMPLOYER_CONTRIBUTION",
    ])
    for slip in payslips:
        gross = Decimal(str(slip.gross_earnings or 0))
        if gross > _ESI_THRESHOLD:
            continue
        emp = employees.get(str(slip.employee_id))
        if not emp:
            continue

        esi_emp = Decimal(str(slip.india_esi_employee or 0))
        esi_er = Decimal(str(slip.india_esi_employer or 0))

        w.writerow([
            emp.esi_number or "",
            emp.full_name,
            f"{gross:.2f}",
            f"{gross:.2f}",
            f"{esi_emp:.2f}",
            f"{esi_er:.2f}",
        ])
    return buf.getvalue()


def generate_wps_sif(payslips: list, employees: dict, bank_details: dict, tenant, payment_date: date) -> str:
    """
    UAE Wages Protection System (WPS) Salary Information File.

    Produces a pipe-delimited SIF per MOHRE WPS specification.
    bank_details: {str(employee_id): EmployeeBankDetail ORM object or None}
    tenant.settings may contain 'mol_employer_id' and 'wps_agent_id'.
    """
    settings = tenant.settings or {}
    mol_employer_id = settings.get("mol_employer_id", tenant.slug.upper())
    agent_id = settings.get("wps_agent_id", "")
    file_date = date.today().strftime("%d%m%Y")
    pay_date = payment_date.strftime("%d%m%Y")
    file_ref = f"WPS{file_date}"

    lines = []
    total_amount = Decimal("0")
    count = 0

    for slip in payslips:
        emp = employees.get(str(slip.employee_id))
        if not emp:
            continue
        bank = bank_details.get(str(slip.employee_id))
        iban = (bank.iban or "") if bank else ""
        net = Decimal(str(slip.net_pay or 0))

        lines.append("|".join([
            "EFT",
            emp.employee_number,
            emp.full_name,
            emp.emirates_id or "",
            iban,
            f"{net:.2f}",
            "AED",
            pay_date,
            file_ref,
        ]))
        total_amount += net
        count += 1

    edr = "|".join([
        "EDR", mol_employer_id, agent_id,
        file_date, pay_date, file_ref,
        "AED", str(count), f"{total_amount:.2f}",
    ])
    eof = f"EOF|{count}|{total_amount:.2f}|AED"
    return "\n".join([edr] + lines + [eof])


def generate_neft_file(payslips: list, employees: dict, bank_details: dict, tenant) -> str:
    """
    NEFT bulk salary payment CSV (India).
    bank_details: {str(employee_id): EmployeeBankDetail ORM object or None}
    """
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow([
        "BENEFICIARY_NAME", "BANK_NAME", "IFSC_CODE", "ACCOUNT_NUMBER",
        "ACCOUNT_TYPE", "AMOUNT", "PAYMENT_REMARKS",
    ])
    for slip in payslips:
        emp = employees.get(str(slip.employee_id))
        if not emp:
            continue
        bank = bank_details.get(str(slip.employee_id))
        net = Decimal(str(slip.net_pay or 0))
        w.writerow([
            emp.full_name,
            bank.bank_name if bank else "",
            bank.ifsc_code if bank else "",
            bank.account_number_encrypted if bank else "",
            (bank.account_type or "savings").upper() if bank else "SAVINGS",
            f"{net:.2f}",
            f"Salary {slip.month:02d}/{slip.year} - {emp.employee_number}",
        ])
    return buf.getvalue()


def generate_tally_xml(payslips: list, employees: dict, year: int, month: int, tenant) -> str:
    """
    Tally Prime / Tally 9 XML import — one payroll voucher per employee.
    Ledger names match what the accountant has set up in Tally (earnings/deductions
    as mapped from payslip JSON keys).
    """
    envelope = ET.Element("ENVELOPE")

    header = ET.SubElement(envelope, "HEADER")
    ET.SubElement(header, "VERSION").text = "1"
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"

    body = ET.SubElement(envelope, "BODY")
    imp = ET.SubElement(body, "IMPORTDATA")

    req_desc = ET.SubElement(imp, "REQUESTDESC")
    ET.SubElement(req_desc, "REPORTNAME").text = "Vouchers"
    ET.SubElement(req_desc, "STATICVARIABLES")

    req_data = ET.SubElement(imp, "REQUESTDATA")

    month_label = date(year, month, 1).strftime("%B %Y")
    voucher_date = f"{year}{month:02d}28"  # 28th is valid in every month

    for slip in payslips:
        emp = employees.get(str(slip.employee_id))
        if not emp:
            continue

        msg = ET.SubElement(req_data, "TALLYMESSAGE")
        msg.set("xmlns:UDF", "TallyUDF")

        v = ET.SubElement(msg, "VOUCHER")
        v.set("ACTION", "Create")
        v.set("VCHTYPE", "Journal")

        ET.SubElement(v, "DATE").text = voucher_date
        ET.SubElement(v, "VOUCHERTYPENAME").text = "Journal"
        ET.SubElement(v, "NARRATION").text = f"Salary for {month_label} — {emp.employee_number} {emp.full_name}"

        earnings = slip.earnings or {}
        deductions = slip.deductions or {}

        # Credit: salary expense ledger entries (one per earning component)
        for key, amount in earnings.items():
            _add_ledger_entry(v, key.replace("_", " ").title(), str(amount), is_debit=False)

        # Debit: net pay ledger (Salary Payable)
        net = Decimal(str(slip.net_pay or 0))
        _add_ledger_entry(v, "Salary Payable", str(net), is_debit=True)

        # Debit: statutory deduction ledgers
        for key, amount in deductions.items():
            _add_ledger_entry(v, key.replace("_", " ").title(), str(amount), is_debit=True)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(envelope, encoding="unicode")


def _add_ledger_entry(voucher_elem, ledger_name: str, amount: str, is_debit: bool) -> None:
    entry = ET.SubElement(voucher_elem, "ALLLEDGERENTRIES.LIST")
    ET.SubElement(entry, "LEDGERNAME").text = ledger_name
    amt = Decimal(str(amount or 0))
    # Tally convention: debit is positive, credit is negative
    signed = str(amt) if is_debit else str(-amt)
    ET.SubElement(entry, "AMOUNT").text = signed
    ET.SubElement(entry, "ISDEEMEDPOSITIVE").text = "Yes" if is_debit else "No"
