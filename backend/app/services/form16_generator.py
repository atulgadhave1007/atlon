from io import BytesIO
from decimal import Decimal


def generate_form16_pdf(employee, payslips: list, tax_decl, tenant, year: int) -> bytes:
    """
    Produce a Form 16 PDF (India TDS annual certificate).
    Part A: quarterly TDS deducted & deposited.
    Part B: salary breakup + Chapter VI-A deductions.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
    )

    def _style(name, **kw):
        return ParagraphStyle(name, **kw)

    S_TITLE = _style("ttl", fontSize=13, fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=3)
    S_SUB = _style("sub", fontSize=8, alignment=TA_CENTER, spaceAfter=4)
    S_H2 = _style("h2", fontSize=10, fontName="Helvetica-Bold", spaceAfter=3, spaceBefore=10)
    S_BODY = _style("body", fontSize=9, spaceAfter=2)
    S_DECL = _style("decl", fontSize=7.5, textColor=colors.grey, spaceBefore=14)

    fiscal_year = f"{year}-{str(year + 1)[-2:]}"
    assessment_year = f"{year + 1}-{str(year + 2)[-2:]}"

    def _tds_for(months):
        return sum(Decimal(str(p.india_tds or 0)) for p in payslips if p.month in months)

    total_gross = sum(Decimal(str(p.gross_earnings or 0)) for p in payslips)
    total_tds = _tds_for(range(1, 13))
    total_pt = sum(Decimal(str(p.india_pt or 0)) for p in payslips)
    total_pf_emp = sum(Decimal(str(p.india_pf_employee or 0)) for p in payslips)

    sec_80c = Decimal(str(tax_decl.section_80c if tax_decl else 0))
    sec_80ccd = Decimal(str(tax_decl.section_80ccd if tax_decl else 0))
    sec_80d = Decimal(str(tax_decl.section_80d if tax_decl else 0))
    sec_80e = Decimal(str(tax_decl.section_80e if tax_decl else 0))
    home_loan = Decimal(str(tax_decl.home_loan_interest if tax_decl else 0))
    total_deductions = sec_80c + sec_80ccd + sec_80d + sec_80e + home_loan
    taxable_income = max(Decimal("0"), total_gross - total_deductions)

    HDR = colors.HexColor("#1e3a8a")
    ALT = colors.HexColor("#f8fafc")
    FOOT_BG = colors.HexColor("#f0fdf4")

    def _tbl(data, col_widths, bold_last=False):
        ts = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HDR),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ALT]),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
        if bold_last:
            ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
            ts.add("BACKGROUND", (0, -1), (-1, -1), FOOT_BG)
        return Table(data, colWidths=col_widths, style=ts)

    def _fmt(v):
        return f"₹ {float(v):,.2f}"

    elems = []

    # ── Header ────────────────────────────────────────────────────────────────
    elems.append(Paragraph("FORM NO. 16", S_TITLE))
    elems.append(Paragraph("[See rule 31(1)(a)]", S_SUB))
    elems.append(Paragraph(
        "Certificate under section 203 of the Income-tax Act, 1961 "
        "for tax deducted at source on salary", S_SUB,
    ))
    elems.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#94a3b8")))
    elems.append(Spacer(1, 8))

    # Employer / employee info
    info = [
        ["Employer Name & Address:", tenant.name or "—",
         "Name of Employee:", employee.full_name],
        ["TAN of Deductor:", tenant.tan or "—",
         "PAN of Employee:", employee.pan or "—"],
        ["Assessment Year:", assessment_year,
         "Period:", f"01/04/{year} to 31/03/{year + 1}"],
    ]
    elems.append(_tbl(info, [4.5 * cm, 6 * cm, 4.5 * cm, 5 * cm]))
    elems.append(Spacer(1, 10))

    # ── Part A: Quarterly TDS ─────────────────────────────────────────────────
    elems.append(Paragraph("PART A — Summary of Tax Deducted & Deposited", S_H2))
    elems.append(Paragraph(f"Financial Year: {fiscal_year}", S_BODY))

    quarters = [
        ("Q1 (Apr–Jun)", [4, 5, 6]),
        ("Q2 (Jul–Sep)", [7, 8, 9]),
        ("Q3 (Oct–Dec)", [10, 11, 12]),
        ("Q4 (Jan–Mar)", [1, 2, 3]),
    ]
    parta_rows = [["Quarter", "Tax Deducted (₹)", "Tax Deposited (₹)"]]
    for label, months in quarters:
        amt = _tds_for(months)
        parta_rows.append([label, _fmt(amt), _fmt(amt)])
    parta_rows.append(["Total", _fmt(total_tds), _fmt(total_tds)])
    elems.append(_tbl(parta_rows, [7 * cm, 6 * cm, 7 * cm], bold_last=True))
    elems.append(Spacer(1, 10))

    # ── Part B: Salary Breakup ────────────────────────────────────────────────
    elems.append(Paragraph("PART B — Computation of Income under Head Salaries", S_H2))

    partb_rows = [
        ["Particulars", "Amount (₹)"],
        ["1.  Gross Salary [u/s 17(1)]", _fmt(total_gross)],
        ["2a. Section 80C (PF, LIC, ELSS, etc.)", _fmt(sec_80c)],
        ["2b. Section 80CCD (NPS)", _fmt(sec_80ccd)],
        ["2c. Section 80D (Health Insurance)", _fmt(sec_80d)],
        ["2d. Section 80E (Education Loan Interest)", _fmt(sec_80e)],
        ["2e. Section 24(b) Home Loan Interest", _fmt(home_loan)],
        ["    Total Deductions (Chapter VI-A)", _fmt(total_deductions)],
        ["3.  Total Taxable Income (1 – 2)", _fmt(taxable_income)],
        ["4.  Tax on Total Income (TDS for FY " + fiscal_year + ")", _fmt(total_tds)],
        ["5.  Professional Tax Deducted", _fmt(total_pt)],
        ["6.  Employee PF Contribution", _fmt(total_pf_emp)],
    ]
    elems.append(_tbl(partb_rows, [13.5 * cm, 6.5 * cm], bold_last=True))
    elems.append(Spacer(1, 10))

    elems.append(Paragraph(
        f"I, {tenant.name or 'the Employer'}, hereby declare that the information furnished above "
        "is true and correct to the best of my knowledge and belief. "
        "This certificate has been generated by Atlon HRMS.",
        S_DECL,
    ))

    doc.build(elems)
    return buf.getvalue()
