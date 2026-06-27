from app.tasks.celery_app import celery
from app.extensions import db
import structlog

log = structlog.get_logger()


@celery.task(name='app.tasks.attendance_tasks.mark_absent_for_previous_day', bind=True, max_retries=2)
def mark_absent_for_previous_day(self):
    from app import create_app
    from app.models import Tenant, Employee, Attendance, Shift, Holiday, LeaveApplication
    from datetime import date, timedelta

    flask_app = create_app()
    with flask_app.app_context():
        target_date = date.today() - timedelta(days=1)
        tenants = Tenant.query.filter_by(status='active', is_deleted=False).all()
        marked = 0

        for tenant in tenants:
            try:
                is_holiday = Holiday.query.filter_by(
                    tenant_id=tenant.id,
                    date=target_date,
                    is_deleted=False
                ).first()

                employees = Employee.active().filter_by(tenant_id=tenant.id).all()
                for emp in employees:
                    existing = Attendance.query.filter_by(
                        tenant_id=tenant.id,
                        employee_id=emp.id,
                        date=target_date
                    ).first()
                    if existing:
                        continue

                    on_leave = LeaveApplication.query.filter_by(
                        tenant_id=tenant.id,
                        employee_id=emp.id,
                        status='approved'
                    ).filter(
                        LeaveApplication.from_date <= target_date,
                        LeaveApplication.to_date >= target_date
                    ).first()

                    shift = None
                    if emp.shift_id:
                        shift = Shift.query.get(emp.shift_id)

                    weekoff_days = shift.week_off_days if shift else [6, 0]
                    is_weekoff = target_date.weekday() in weekoff_days

                    if on_leave:
                        status = 'on_leave'
                    elif is_holiday:
                        status = 'holiday'
                    elif is_weekoff:
                        status = 'weekly_off'
                    else:
                        status = 'absent'

                    att = Attendance(
                        tenant_id=tenant.id,
                        employee_id=emp.id,
                        date=target_date,
                        status=status,
                        source='system'
                    )
                    db.session.add(att)
                    marked += 1

                db.session.commit()
            except Exception as e:
                db.session.rollback()
                log.error('mark_absent_failed', tenant=tenant.slug, error=str(e))

        log.info('mark_absent_done', date=str(target_date), marked=marked)
        return {'marked': marked}


@celery.task(name='app.tasks.attendance_tasks.process_biometric_queue', bind=True)
def process_biometric_queue(self):
    from app import create_app
    from app.models import BiometricLog
    from app.api.v1.biometric import _process_biometric_logs

    flask_app = create_app()
    with flask_app.app_context():
        unprocessed = BiometricLog.query.filter_by(processed=False).limit(500).all()
        processed = 0
        for log_entry in unprocessed:
            try:
                _process_biometric_logs(log_entry.tenant_id, [log_entry])
                log_entry.processed = True
                processed += 1
            except Exception as e:
                log.error('biometric_process_failed', id=str(log_entry.id), error=str(e))
        db.session.commit()
        return {'processed': processed}
