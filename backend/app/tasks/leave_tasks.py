from app.tasks.celery_app import celery
from app.extensions import db
import structlog

log = structlog.get_logger()


@celery.task(name='app.tasks.leave_tasks.accrue_leave_all_tenants', bind=True, max_retries=3)
def accrue_leave_all_tenants(self):
    from app import create_app
    from app.models import Tenant, LeaveType, LeaveBalance, Employee
    from decimal import Decimal
    from datetime import date

    flask_app = create_app()
    with flask_app.app_context():
        tenants = Tenant.query.filter_by(status='active', is_deleted=False).all()
        total = 0
        for tenant in tenants:
            try:
                leave_types = LeaveType.query.filter_by(
                    tenant_id=tenant.id,
                    is_deleted=False,
                    accrual_enabled=True
                ).all()
                employees = Employee.active().filter_by(tenant_id=tenant.id).all()

                for emp in employees:
                    for lt in leave_types:
                        balance = LeaveBalance.query.filter_by(
                            tenant_id=tenant.id,
                            employee_id=emp.id,
                            leave_type_id=lt.id
                        ).first()
                        if not balance:
                            balance = LeaveBalance(
                                tenant_id=tenant.id,
                                employee_id=emp.id,
                                leave_type_id=lt.id,
                                balance=Decimal('0'),
                                accrued=Decimal('0'),
                                availed=Decimal('0'),
                                year=date.today().year
                            )
                            db.session.add(balance)

                        monthly_accrual = Decimal(str(lt.days_per_year)) / 12
                        balance.balance += monthly_accrual
                        balance.accrued += monthly_accrual

                        if lt.max_carry_forward is not None and balance.balance > Decimal(str(lt.max_carry_forward)):
                            balance.balance = Decimal(str(lt.max_carry_forward))
                        total += 1

                db.session.commit()
                log.info('leave_accrual_tenant_done', tenant=tenant.slug, employees=len(employees))
            except Exception as e:
                db.session.rollback()
                log.error('leave_accrual_tenant_failed', tenant=tenant.slug, error=str(e))

        log.info('leave_accrual_complete', total_balances_updated=total)
        return {'updated': total}


@celery.task(name='app.tasks.leave_tasks.expire_leave_balances', bind=True)
def expire_leave_balances(self):
    from app import create_app
    from app.models import LeaveType, LeaveBalance
    from datetime import date
    from decimal import Decimal

    flask_app = create_app()
    with flask_app.app_context():
        today = date.today()
        if today.month != 1 or today.day != 1:
            return {'message': 'Not year start — skipping'}

        prev_year = today.year - 1
        no_carry = LeaveType.query.filter_by(max_carry_forward=0, is_deleted=False).all()
        expired = 0
        for lt in no_carry:
            LeaveBalance.query.filter_by(
                leave_type_id=lt.id, year=prev_year
            ).update({'balance': Decimal('0')})
            expired += 1

        db.session.commit()
        log.info('leave_expiry_done', types_processed=expired)
        return {'expired': expired}
