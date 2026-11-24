"""
DEMO ONLY. Seeds a fake company with sample employees and activity data.

    python seed_demo.py

Every account created here shares the publicly documented password
"Demo@1234". Never run this against a database real people use.
The script refuses to run when FLASK_ENV=production.
"""
import os
import sys
import random
import uuid
from datetime import date, time, datetime, timedelta, timezone
from decimal import Decimal

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
if os.environ.get('FLASK_ENV', '').strip().lower() == 'production':
    sys.exit('seed_demo.py is DEMO ONLY and refuses to run with FLASK_ENV=production.')
os.environ.setdefault('FLASK_ENV', 'development')

# Publicly documented demo password. DEMO ONLY: do not reuse anywhere.
DEMO_PASSWORD = 'Demo@1234'

from app import create_app
from app.extensions import db
from app.models import (
    Tenant, Plan, Employee, Department, Designation,
    LeaveType, LeaveBalance, Holiday, Shift, EmployeeSalary,
    PlanTier, LeaveApplication, LeaveApplicationStatus,
)
from app.models.tenant import TenantStatus, CountryCode
from app.models.attendance import HolidayType, EmployeeShift, Attendance, AttendanceStatus, AttendanceSource
from app.models.leave import LeaveAccrualType
from app.models.employee import Gender, BloodGroup, EmployeeStatus, EmploymentType
from app.models.payroll import PayrollRun, Payslip, PayrollStatus
from app.models.helpdesk import HelpTicket, TicketPriority, TicketStatus, Announcement, TicketCategory
from app.models.expense import ExpenseClaim, ExpenseStatus, ExpenseItem
from app.utils.security import hash_password

app = create_app()


def seed():
    with app.app_context():
        print('Seeding demo data...')

        # Ensure a plan exists
        plan = Plan.query.filter_by(name='standard').first()
        if not plan:
            plan = Plan(
                name='standard',
                tier=PlanTier.STANDARD,
                display_name='Standard',
                price_per_employee_inr=120,
                price_per_employee_usd=2,
                max_employees=500,
                max_admins=5,
                features={"attendance": True, "leave": True, "payroll": True},
            )
            db.session.add(plan)
            db.session.flush()

        # Find or create demo tenant
        tenant = Tenant.query.filter_by(slug='demo').first()
        if not tenant:
            tenant = Tenant(
                name='Demo Technologies Pvt. Ltd.',
                slug='demo',
                email='hr@demo.com',
                country=CountryCode.IN,
                timezone='Asia/Kolkata',
                currency='INR',
                status=TenantStatus.ACTIVE,
                plan_id=plan.id,
            )
            db.session.add(tenant)
            db.session.flush()
            print(f'Created tenant: {tenant.slug} ({tenant.id})')
        else:
            print(f'Using existing tenant: {tenant.slug}')

        # Departments
        dept_names = ['Engineering', 'Product', 'Marketing', 'Sales', 'HR', 'Finance', 'Operations']
        depts = {}
        for name in dept_names:
            d = Department.query.filter_by(tenant_id=tenant.id, name=name).first()
            if not d:
                d = Department(tenant_id=tenant.id, name=name, code=name[:3].upper())
                db.session.add(d)
            depts[name] = d
        db.session.flush()

        # Designations
        desig_names = [
            'Software Engineer', 'Senior Engineer', 'Tech Lead', 'Engineering Manager',
            'Product Manager', 'Designer', 'HR Executive', 'HR Manager',
            'Sales Executive', 'Finance Analyst', 'CEO', 'CTO',
        ]
        desigs = {}
        for name in desig_names:
            d = Designation.query.filter_by(tenant_id=tenant.id, name=name).first()
            if not d:
                d = Designation(tenant_id=tenant.id, name=name)
                db.session.add(d)
            desigs[name] = d
        db.session.flush()

        # Default Shift — use actual model field names
        shift = Shift.query.filter_by(tenant_id=tenant.id, name='General').first()
        if not shift:
            shift = Shift(
                tenant_id=tenant.id,
                name='General',
                code='GEN',
                start_time=time(9, 0),
                end_time=time(18, 0),
                grace_in_minutes=15,
                grace_out_minutes=15,
                min_hours=Decimal('9.0'),
                half_day_hours=Decimal('4.5'),
                weekoff_days=['saturday', 'sunday'],
                break_duration_minutes=60,
            )
            db.session.add(shift)
        db.session.flush()

        # Leave types — (name, code, annual_days, is_accrual, carry_forward_days)
        # annual_days drives opening_balance in LeaveBalance; stored separately since LeaveType
        # uses max_balance for cap, not days_per_year.
        leave_types_data = [
            ('Casual Leave',    'CL',  12,  True,  6),
            ('Sick Leave',      'SL',  8,   False, 0),
            ('Privilege Leave', 'PL',  15,  True,  15),
            ('Maternity Leave', 'ML',  182, False, 0),
            ('Paternity Leave', 'PAL', 10,  False, 0),
            ('Comp Off',        'CO',  0,   False, 30),
        ]
        leave_types = []     # list of (lt_model, annual_days)
        for name, code, days, is_accrual, carry in leave_types_data:
            lt = LeaveType.query.filter_by(tenant_id=tenant.id, name=name).first()
            if not lt:
                lt = LeaveType(
                    tenant_id=tenant.id,
                    name=name,
                    code=code,
                    max_balance=Decimal(str(max(days, 30))),
                    max_carry_forward=Decimal(str(carry)),
                    accrual_type=(LeaveAccrualType.MONTHLY if is_accrual else LeaveAccrualType.MANUAL),
                    accrual_days_per_period=Decimal(str(round(days / 12, 2))) if days > 0 else Decimal('0'),
                    is_paid=True,
                    max_days_per_application=Decimal(str(days if days > 0 else 30)),
                )
                db.session.add(lt)
            leave_types.append((lt, days))
        db.session.flush()

        # Holidays — map 'festival' → OPTIONAL since HolidayType has no FESTIVAL value
        _htype_map = {
            'national': HolidayType.NATIONAL,
            'regional': HolidayType.REGIONAL,
            'optional': HolidayType.OPTIONAL,
            'festival': HolidayType.OPTIONAL,
            'company':  HolidayType.COMPANY,
        }
        holidays_data = [
            (date(2025, 1, 26),  'Republic Day',           'national'),
            (date(2025, 3, 14),  'Holi',                   'festival'),
            (date(2025, 4, 14),  'Dr. Ambedkar Jayanti',   'national'),
            (date(2025, 4, 18),  'Good Friday',            'festival'),
            (date(2025, 5, 1),   'Labour Day',             'national'),
            (date(2025, 8, 15),  'Independence Day',       'national'),
            (date(2025, 10, 2),  'Gandhi Jayanti',         'national'),
            (date(2025, 10, 20), 'Diwali',                 'festival'),
            (date(2025, 12, 25), 'Christmas',              'festival'),
            (date(2026, 1, 26),  'Republic Day',           'national'),
            (date(2026, 8, 15),  'Independence Day',       'national'),
            (date(2026, 10, 2),  'Gandhi Jayanti',         'national'),
            (date(2026, 12, 25), 'Christmas',              'festival'),
        ]
        for h_date, h_name, h_type_str in holidays_data:
            if not Holiday.query.filter_by(tenant_id=tenant.id, date=h_date).first():
                h = Holiday(
                    tenant_id=tenant.id,
                    name=h_name,
                    date=h_date,
                    type=_htype_map.get(h_type_str, HolidayType.NATIONAL),
                    year=h_date.year,
                )
                db.session.add(h)
        db.session.flush()

        # Employees
        employees_data = [
            ('Arjun Mehta',   'arjun@demo.com',   'Engineering', 'CTO',                  'hr_admin', 3000000),
            ('Priya Sharma',  'priya@demo.com',   'HR',          'HR Manager',            'hr_admin', 1200000),
            ('Rahul Gupta',   'rahul@demo.com',   'Engineering', 'Engineering Manager',   'manager',  2000000),
            ('Neha Singh',    'neha@demo.com',    'Product',     'Product Manager',       'manager',  1800000),
            ('Amit Patel',    'amit@demo.com',    'Engineering', 'Software Engineer',     'employee',  900000),
            ('Kavya Reddy',   'kavya@demo.com',   'Engineering', 'Software Engineer',     'employee',  800000),
            ('Suresh Kumar',  'suresh@demo.com',  'Sales',       'Sales Executive',       'employee',  700000),
            ('Deepika Nair',  'deepika@demo.com', 'Finance',     'Finance Analyst',       'employee',  750000),
            ('Rajesh Joshi',  'rajesh@demo.com',  'Marketing',   'Designer',              'employee',  650000),
            ('Ananya Iyer',   'ananya@demo.com',  'Engineering', 'Senior Engineer',       'employee', 1200000),
        ]

        created_employees = []
        for i, (name, email, dept_name, desig_name, role, ctc) in enumerate(employees_data):
            existing = Employee.query.filter_by(tenant_id=tenant.id, work_email=email).first()
            if existing:
                created_employees.append(existing)
                continue

            emp_num = f'EMP{i + 1:03d}'
            password_hash = hash_password(DEMO_PASSWORD)
            dob = date(1990 + (i % 8), (i % 12) + 1, (i % 28) + 1)
            joining = date(2022, (i % 12) + 1, (i % 28) + 1)

            emp = Employee(
                tenant_id=tenant.id,
                employee_number=emp_num,
                first_name=name.split()[0],
                last_name=' '.join(name.split()[1:]),
                work_email=email,
                personal_phone=f'+919{random.randint(100000000, 999999999)}',
                password_hash=password_hash,
                role=role,
                status=EmployeeStatus.ACTIVE,
                employment_type=EmploymentType.FULL_TIME,
                date_of_joining=joining,
                date_of_birth=dob,
                gender=random.choice([Gender.MALE, Gender.FEMALE]),
                blood_group=random.choice([BloodGroup.A_POS, BloodGroup.B_POS, BloodGroup.O_POS, BloodGroup.AB_POS]),
                pan=f'ABCDE{i + 1:04d}F',
                pf_number=f'MH/PY/1234/000/{i + 1:04d}',
                department_id=str(depts[dept_name].id) if dept_name in depts else None,
                designation_id=str(desigs[desig_name].id) if desig_name in desigs else None,
                force_password_change=False,
            )
            db.session.add(emp)
            db.session.flush()

            # Assign default shift via EmployeeShift join model
            db.session.add(EmployeeShift(
                tenant_id=tenant.id,
                employee_id=str(emp.id),
                shift_id=str(shift.id),
                effective_from=joining,
            ))

            # Salary — use actual EmployeeSalary field names
            monthly_ctc = Decimal(str(ctc)) / 12
            india_basic = monthly_ctc * Decimal('0.4')
            india_hra = monthly_ctc * Decimal('0.2')
            special = monthly_ctc - india_basic - india_hra

            salary = EmployeeSalary(
                tenant_id=tenant.id,
                employee_id=str(emp.id),
                ctc_annual=Decimal(str(ctc)),
                ctc_monthly=monthly_ctc,
                india_basic=india_basic,
                india_hra=india_hra,
                components={'Special Allowance': float(special)},
                effective_from=joining,
            )
            db.session.add(salary)

            # Leave balances — use actual LeaveBalance field names
            for lt, annual_days in leave_types:
                existing_bal = LeaveBalance.query.filter_by(
                    tenant_id=tenant.id,
                    employee_id=str(emp.id),
                    leave_type_id=str(lt.id),
                    year=date.today().year,
                ).first()
                if not existing_bal:
                    bal = LeaveBalance(
                        tenant_id=tenant.id,
                        employee_id=str(emp.id),
                        leave_type_id=str(lt.id),
                        year=date.today().year,
                        opening_balance=Decimal(str(annual_days)) if annual_days > 0 else Decimal('0'),
                        credited=Decimal(str(annual_days)) if annual_days > 0 else Decimal('0'),
                        availed=Decimal('0'),
                    )
                    db.session.add(bal)

            created_employees.append(emp)
            print(f'  Created employee: {name} ({email}) — DEMO password: {DEMO_PASSWORD}')

        db.session.commit()
        print(f'\nBase seeding complete — seeding activity data...')
        seed_activity(app, tenant, created_employees, shift, leave_types)
        print(f'\nDemo seeding complete!')
        print(f'  Tenant slug : demo')
        print(f'  Employees   : {len(created_employees)}')
        print(f'  Login URL   : http://localhost:5000')
        print(f'  ---- DEMO ONLY credentials (publicly known, do not use in production) ----')
        print(f'  HR Admin  : EMP001 / {DEMO_PASSWORD}  (Arjun Mehta)')
        print(f'  Manager   : EMP003 / {DEMO_PASSWORD}  (Rahul Gupta)')
        print(f'  Employee  : EMP005 / {DEMO_PASSWORD}  (Amit Patel)')
        print(f'  Company ID for login : demo')
        print(f'  Super admin is NOT created by this script; it comes from')
        print(f'  SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD in backend/.env.')


def seed_activity(app, tenant, employees, shift, leave_types):
    """Seed attendance, payslips, leave applications, tickets, announcements, expenses."""
    with app.app_context():
        tenant = db.session.merge(tenant)
        employees = [db.session.merge(e) for e in employees]
        shift = db.session.merge(shift)
        leave_types_merged = [(db.session.merge(lt), d) for lt, d in leave_types]

        today = date.today()
        hr_admin = employees[0]  # Arjun — hr_admin

        # ── Attendance: past 90 calendar days ──────────────────────────────────
        print('  Seeding attendance records...')
        holidays_set = {
            h.date for h in Holiday.query.filter_by(
                tenant_id=tenant.id, is_deleted=False
            ).all()
        }
        for emp in employees:
            for offset in range(90):
                d = today - timedelta(days=offset + 1)
                if Attendance.query.filter_by(
                    tenant_id=tenant.id, employee_id=str(emp.id), date=d, is_deleted=False
                ).first():
                    continue
                weekday = d.weekday()
                is_weekend = weekday >= 5
                is_holiday = d in holidays_set

                if is_holiday:
                    att = Attendance(
                        id=uuid.uuid4(), tenant_id=tenant.id,
                        employee_id=str(emp.id), date=d,
                        status=AttendanceStatus.HOLIDAY, shift_id=str(shift.id),
                    )
                elif is_weekend:
                    att = Attendance(
                        id=uuid.uuid4(), tenant_id=tenant.id,
                        employee_id=str(emp.id), date=d,
                        status=AttendanceStatus.WEEKLY_OFF, shift_id=str(shift.id),
                    )
                else:
                    roll = random.random()
                    if roll < 0.05:
                        # Absent
                        att = Attendance(
                            id=uuid.uuid4(), tenant_id=tenant.id,
                            employee_id=str(emp.id), date=d,
                            status=AttendanceStatus.ABSENT, shift_id=str(shift.id),
                        )
                    elif roll < 0.12:
                        # WFH
                        ci_hour = random.randint(9, 10)
                        ci_min = random.randint(0, 30)
                        co_hour = random.randint(18, 19)
                        ci = datetime(d.year, d.month, d.day, ci_hour, ci_min, tzinfo=timezone.utc)
                        co = datetime(d.year, d.month, d.day, co_hour, random.randint(0, 59), tzinfo=timezone.utc)
                        att = Attendance(
                            id=uuid.uuid4(), tenant_id=tenant.id,
                            employee_id=str(emp.id), date=d,
                            status=AttendanceStatus.WORK_FROM_HOME,
                            check_in=ci, check_out=co,
                            working_hours=Decimal(str(round((co - ci).seconds / 3600, 2))),
                            check_in_source=AttendanceSource.WEB,
                            check_out_source=AttendanceSource.WEB,
                            shift_id=str(shift.id),
                        )
                    else:
                        # Present
                        ci_hour = random.randint(9, 10)
                        ci_min = random.randint(0, 45)
                        co_hour = random.randint(18, 20)
                        late = (ci_hour == 10 and ci_min > 15)
                        ci = datetime(d.year, d.month, d.day, ci_hour, ci_min, tzinfo=timezone.utc)
                        co = datetime(d.year, d.month, d.day, co_hour, random.randint(0, 59), tzinfo=timezone.utc)
                        worked = Decimal(str(round((co - ci).seconds / 3600, 2)))
                        att = Attendance(
                            id=uuid.uuid4(), tenant_id=tenant.id,
                            employee_id=str(emp.id), date=d,
                            status=AttendanceStatus.LATE if late else AttendanceStatus.PRESENT,
                            check_in=ci, check_out=co,
                            working_hours=worked,
                            late_minutes=(ci_hour * 60 + ci_min - 9 * 60 - 15) if late else 0,
                            check_in_source=AttendanceSource.WEB,
                            check_out_source=AttendanceSource.WEB,
                            shift_id=str(shift.id),
                        )
                db.session.add(att)
        db.session.commit()
        print(f'    Attendance records seeded.')

        # ── Payroll Runs + Payslips: last 6 months ─────────────────────────────
        print('  Seeding payslips...')
        for mo_offset in range(1, 7):
            target = today.replace(day=1) - timedelta(days=mo_offset * 28)
            yr, mo = target.year, target.month

            run = PayrollRun.query.filter_by(
                tenant_id=tenant.id, year=yr, month=mo, is_deleted=False
            ).first()
            if not run:
                run = PayrollRun(
                    id=uuid.uuid4(), tenant_id=tenant.id,
                    year=yr, month=mo,
                    name=f"Payroll {target.strftime('%B %Y')}",
                    status=PayrollStatus.DISBURSED,
                    employee_count=len(employees),
                    processed_at=datetime(yr, mo, 28, 12, 0, tzinfo=timezone.utc),
                    disbursed_at=datetime(yr, mo, 28, 14, 0, tzinfo=timezone.utc),
                    processed_by_id=str(hr_admin.id),
                    disbursed_by_id=str(hr_admin.id),
                )
                db.session.add(run)
                db.session.flush()

            for emp in employees:
                if Payslip.query.filter_by(
                    tenant_id=tenant.id, employee_id=str(emp.id),
                    year=yr, month=mo, is_deleted=False
                ).first():
                    continue
                sal = EmployeeSalary.query.filter_by(
                    tenant_id=tenant.id, employee_id=str(emp.id),
                    effective_to=None, is_deleted=False
                ).first()
                monthly = float(sal.ctc_monthly) if sal and sal.ctc_monthly else 50000.0
                basic = round(monthly * 0.4, 2)
                hra = round(monthly * 0.2, 2)
                special = round(monthly - basic - hra, 2)
                pf_emp = round(min(basic, 15000) * 0.12, 2)
                pf_er = pf_emp
                pt = 200.0
                tds = round(max(0, monthly * 12 - 250000) * 0.05 / 12, 2)
                total_ded = round(pf_emp + pt + tds, 2)
                net = round(monthly - total_ded, 2)

                slip = Payslip(
                    id=uuid.uuid4(), tenant_id=tenant.id,
                    payroll_run_id=str(run.id),
                    employee_id=str(emp.id),
                    year=yr, month=mo,
                    working_days=26, paid_days=Decimal('26'), lop_days=Decimal('0'),
                    earnings={'Basic': basic, 'HRA': hra, 'Special Allowance': special},
                    deductions={'PF Employee': pf_emp, 'Professional Tax': pt, 'TDS': tds},
                    employer_contributions={'PF Employer': pf_er},
                    gross_earnings=Decimal(str(monthly)),
                    total_deductions=Decimal(str(total_ded)),
                    net_pay=Decimal(str(net)),
                    employer_total=Decimal(str(pf_er)),
                    india_pf_employee=Decimal(str(pf_emp)),
                    india_pf_employer=Decimal(str(pf_er)),
                    india_pt=Decimal(str(pt)),
                    india_tds=Decimal(str(tds)),
                )
                db.session.add(slip)
        db.session.commit()
        print('    Payslips seeded.')

        # ── Leave Applications ─────────────────────────────────────────────────
        print('  Seeding leave applications...')
        cl_type = next((lt for lt, _ in leave_types_merged if lt.code == 'CL'), None)
        sl_type = next((lt for lt, _ in leave_types_merged if lt.code == 'SL'), None)

        leave_data = [
            # (emp_index, leave_type, from_offset_days_ago, num_days, status, reviewer_idx)
            (4, cl_type, 30, 2, LeaveApplicationStatus.APPROVED, 0),
            (5, cl_type, 20, 1, LeaveApplicationStatus.APPROVED, 0),
            (6, sl_type, 15, 1, LeaveApplicationStatus.APPROVED, 1),
            (7, cl_type, 10, 3, LeaveApplicationStatus.APPROVED, 0),
            (8, sl_type, 45, 2, LeaveApplicationStatus.APPROVED, 1),
            (4, cl_type, 5,  2, LeaveApplicationStatus.PENDING,  None),
            (5, sl_type, 3,  1, LeaveApplicationStatus.PENDING,  None),
            (9, cl_type, 60, 1, LeaveApplicationStatus.REJECTED, 0),
        ]
        for emp_idx, lt, from_offset, num_days, status, reviewer_idx in leave_data:
            if emp_idx >= len(employees) or not lt:
                continue
            emp = employees[emp_idx]
            from_d = today - timedelta(days=from_offset)
            to_d = from_d + timedelta(days=num_days - 1)
            if LeaveApplication.query.filter_by(
                tenant_id=tenant.id, employee_id=str(emp.id),
                from_date=from_d, is_deleted=False
            ).first():
                continue
            reviewer = employees[reviewer_idx] if reviewer_idx is not None else None
            app_obj = LeaveApplication(
                id=uuid.uuid4(), tenant_id=tenant.id,
                employee_id=str(emp.id),
                leave_type_id=str(lt.id),
                from_date=from_d, to_date=to_d,
                days_count=Decimal(str(num_days)),
                reason='Personal reasons' if lt.code == 'CL' else 'Not feeling well',
                status=status,
                reviewed_by_id=str(reviewer.id) if reviewer else None,
                reviewed_at=datetime.now(timezone.utc) - timedelta(days=from_offset - 1) if reviewer else None,
                applied_at=datetime.now(timezone.utc) - timedelta(days=from_offset + 1),
            )
            db.session.add(app_obj)
        db.session.commit()
        print('    Leave applications seeded.')

        # ── Announcements ──────────────────────────────────────────────────────
        print('  Seeding announcements...')
        ann_data = [
            ('Welcome to Atlon HRMS!',
             'We are pleased to launch our new HR management system. All employees can now manage attendance, leaves, and payslips from a single portal.',
             'general', True),
            ('Office Closed — Independence Day',
             'The office will remain closed on 15th August 2025 on account of Independence Day. Enjoy the long weekend!',
             'holiday', True),
            ('Mandatory Policy Update: Work From Home',
             'Effective 1st July 2026, employees may avail WFH on a maximum of 2 days per week. Please submit WFH requests via the portal at least one day in advance.',
             'policy', True),
            ('Q1 Performance Reviews Kick Off',
             'Appraisal cycle for Q1 FY 2026-27 has begun. Employees are requested to complete their self-evaluations by 30th June 2026.',
             'performance', True),
            ('Health Checkup Camp — Register Now',
             'A free health checkup camp will be conducted on 28th June 2026 in the office premises. Please register at the reception desk.',
             'general', True),
        ]
        for title, content, ann_type, target_all in ann_data:
            if Announcement.query.filter_by(
                tenant_id=tenant.id, title=title, is_deleted=False
            ).first():
                continue
            ann = Announcement(
                id=uuid.uuid4(), tenant_id=tenant.id,
                title=title, content=content,
                type=ann_type, target_all=target_all,
                created_by_id=str(hr_admin.id),
                is_pinned=(ann_type == 'policy'),
            )
            db.session.add(ann)
        db.session.commit()
        print('    Announcements seeded.')

        # ── Help Desk Tickets ──────────────────────────────────────────────────
        print('  Seeding help desk tickets...')
        cat = TicketCategory.query.filter_by(tenant_id=tenant.id, is_deleted=False).first()
        ticket_data = [
            (4, 'Salary slip for March not visible', 'My payslip for March 2026 is not showing in the portal. Please check.', TicketPriority.HIGH, TicketStatus.RESOLVED),
            (5, 'Unable to apply for leave', 'Getting an error when trying to apply Casual Leave for next week.', TicketPriority.MEDIUM, TicketStatus.OPEN),
            (6, 'Attendance mismatch on 10th June', 'My attendance shows Absent on 10th June 2026 but I was present. Please regularize.', TicketPriority.HIGH, TicketStatus.IN_PROGRESS),
            (7, 'IT asset request — laptop charger', 'My laptop charger is damaged. Requesting a replacement.', TicketPriority.LOW, TicketStatus.OPEN),
            (8, 'Tax declaration form — query', 'I have a query about filling Section 80C in the tax declaration form.', TicketPriority.MEDIUM, TicketStatus.RESOLVED),
            (9, 'Leave balance incorrect', 'My leave balance shows 5 days but I should have 12 days of Casual Leave remaining.', TicketPriority.HIGH, TicketStatus.PENDING),
        ]
        _counter = HelpTicket.query.filter_by(tenant_id=tenant.id, is_deleted=False).count()
        for emp_idx, title, desc, priority, status in ticket_data:
            if emp_idx >= len(employees):
                continue
            emp = employees[emp_idx]
            _counter += 1
            tkt_num = f'TKT{_counter:07d}'
            if HelpTicket.query.filter_by(
                tenant_id=tenant.id, ticket_number=tkt_num, is_deleted=False
            ).first():
                continue
            tkt = HelpTicket(
                id=uuid.uuid4(), tenant_id=tenant.id,
                ticket_number=tkt_num,
                employee_id=str(emp.id),
                category_id=str(cat.id) if cat else None,
                title=title, description=desc,
                priority=priority, status=status,
                assigned_to_id=str(hr_admin.id),
                resolved_at=datetime.now(timezone.utc) - timedelta(days=2) if status == TicketStatus.RESOLVED else None,
            )
            db.session.add(tkt)
        db.session.commit()
        print('    Help desk tickets seeded.')

        # ── Expense Claims ─────────────────────────────────────────────────────
        print('  Seeding expense claims...')
        exp_data = [
            (4, 'Team Lunch — June 2026', 1850.0, ExpenseStatus.APPROVED),
            (5, 'Client Visit Travel', 4200.0, ExpenseStatus.SUBMITTED),
            (6, 'Conference Registration', 3000.0, ExpenseStatus.APPROVED),
            (7, 'Office Supplies', 650.0, ExpenseStatus.DRAFT),
            (8, 'Training Material', 1200.0, ExpenseStatus.SUBMITTED),
        ]
        _exp_counter = ExpenseClaim.query.filter_by(tenant_id=tenant.id, is_deleted=False).count()
        for emp_idx, title, amount, status in exp_data:
            if emp_idx >= len(employees):
                continue
            emp = employees[emp_idx]
            _exp_counter += 1
            claim_num = f'EXP{today.year}{_exp_counter:05d}'
            if ExpenseClaim.query.filter_by(
                tenant_id=tenant.id, claim_number=claim_num, is_deleted=False
            ).first():
                continue
            claim = ExpenseClaim(
                id=uuid.uuid4(), tenant_id=tenant.id,
                employee_id=str(emp.id),
                claim_number=claim_num,
                title=title,
                total_amount=Decimal(str(amount)),
                approved_amount=Decimal(str(amount)) if status == ExpenseStatus.APPROVED else None,
                currency='INR',
                status=status,
                submitted_at=datetime.now(timezone.utc) - timedelta(days=10) if status != ExpenseStatus.DRAFT else None,
                approved_by_id=str(hr_admin.id) if status == ExpenseStatus.APPROVED else None,
                approved_at=datetime.now(timezone.utc) - timedelta(days=5) if status == ExpenseStatus.APPROVED else None,
            )
            db.session.add(claim)
            db.session.flush()
            item = ExpenseItem(
                id=uuid.uuid4(), tenant_id=tenant.id,
                claim_id=str(claim.id),
                description=title,
                expense_date=today - timedelta(days=12),
                amount=Decimal(str(amount)),
                currency='INR',
            )
            db.session.add(item)
        db.session.commit()
        print('    Expense claims seeded.')


if __name__ == '__main__':
    seed()
