from app.tasks.celery_app import celery
from app.extensions import db
import structlog

log = structlog.get_logger()


@celery.task(name='app.tasks.notification_tasks.send_birthday_notifications', bind=True)
def send_birthday_notifications(self):
    from app import create_app
    from app.models import Tenant, Employee, Notification
    from datetime import date

    flask_app = create_app()
    with flask_app.app_context():
        today = date.today()
        tenants = Tenant.query.filter_by(status='active', is_deleted=False).all()
        sent = 0

        for tenant in tenants:
            birthdays = Employee.active().filter_by(tenant_id=tenant.id).filter(
                db.extract('month', Employee.date_of_birth) == today.month,
                db.extract('day', Employee.date_of_birth) == today.day
            ).all()

            for emp in birthdays:
                notif = Notification(
                    tenant_id=tenant.id,
                    employee_id=emp.id,
                    type='birthday',
                    title=f'Happy Birthday, {emp.full_name}! 🎂',
                    body='Wishing you a wonderful birthday! The entire team wishes you great joy.',
                    channel='in_app'
                )
                db.session.add(notif)

                if emp.work_email:
                    send_template_email.delay(
                        emp.work_email,
                        f'Happy Birthday, {emp.first_name}! 🎂',
                        'email/birthday.html',
                        {'first_name': emp.first_name, 'employee_name': emp.full_name,
                         'company_name': tenant.name},
                    )

                all_employees = Employee.active().filter_by(tenant_id=tenant.id).filter(
                    Employee.id != emp.id
                ).all()
                for other in all_employees[:50]:
                    peer_notif = Notification(
                        tenant_id=tenant.id,
                        employee_id=other.id,
                        type='birthday',
                        title=f"🎂 It's {emp.full_name}'s Birthday!",
                        body=f"Today is {emp.full_name}'s birthday. Wish them well!",
                        channel='in_app'
                    )
                    db.session.add(peer_notif)
                sent += 1

        db.session.commit()
        log.info('birthday_notifications_sent', count=sent)
        return {'sent': sent}


@celery.task(name='app.tasks.notification_tasks.send_anniversary_notifications', bind=True)
def send_anniversary_notifications(self):
    from app import create_app
    from app.models import Tenant, Employee, Notification
    from datetime import date

    flask_app = create_app()
    with flask_app.app_context():
        today = date.today()
        tenants = Tenant.query.filter_by(status='active', is_deleted=False).all()
        sent = 0

        for tenant in tenants:
            anniversaries = Employee.active().filter_by(tenant_id=tenant.id).filter(
                db.extract('month', Employee.date_of_joining) == today.month,
                db.extract('day', Employee.date_of_joining) == today.day,
                Employee.date_of_joining < today
            ).all()

            for emp in anniversaries:
                years = today.year - emp.date_of_joining.year
                if years == 0:
                    continue
                notif = Notification(
                    tenant_id=tenant.id,
                    employee_id=emp.id,
                    type='work_anniversary',
                    title=f'🎉 {years}-Year Work Anniversary!',
                    body=f'Congratulations on {years} year{"s" if years>1 else ""} at the company!',
                    channel='in_app'
                )
                db.session.add(notif)

                if emp.work_email:
                    send_template_email.delay(
                        emp.work_email,
                        f'Congratulations on your {years}-Year Work Anniversary!',
                        'email/work_anniversary.html',
                        {'employee_name': emp.full_name, 'first_name': emp.first_name,
                         'years': years, 'company_name': tenant.name},
                    )
                sent += 1

        db.session.commit()
        log.info('anniversary_notifications_sent', count=sent)
        return {'sent': sent}


@celery.task(name='app.tasks.notification_tasks.send_email_notification', bind=True, max_retries=3)
def send_email_notification(self, recipient_email, subject, html_body):
    from app import create_app
    from app.utils.notifications import send_email

    flask_app = create_app()
    with flask_app.app_context():
        try:
            send_email(recipient_email, subject, html_body, html_body)
            return {'sent': True}
        except Exception as exc:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@celery.task(name='app.tasks.notification_tasks.send_template_email', bind=True, max_retries=3)
def send_template_email(self, to: str, subject: str, template_name: str, context: dict):
    """Render a Jinja2 email template and send via SMTP. Retries up to 3× on failure."""
    from app import create_app
    from app.services.email_service import send_email_template

    flask_app = create_app()
    with flask_app.app_context():
        try:
            send_email_template(to, subject, template_name, context)
            return {'sent': True, 'to': to, 'template': template_name}
        except Exception as exc:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
