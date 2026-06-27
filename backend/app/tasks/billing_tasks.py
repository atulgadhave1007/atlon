from app.tasks.celery_app import celery
import structlog

log = structlog.get_logger()


@celery.task(name='app.tasks.billing_tasks.check_subscription_expiry', bind=True)
def check_subscription_expiry(self):
    from app import create_app
    from app.models import Tenant, Subscription
    from datetime import date, timedelta

    flask_app = create_app()
    with flask_app.app_context():
        from app.extensions import db
        today = date.today()
        expiring_soon = Subscription.query.filter(
            Subscription.end_date <= today + timedelta(days=7),
            Subscription.end_date > today,
            Subscription.status == 'active'
        ).all()

        for sub in expiring_soon:
            days_left = (sub.end_date - today).days
            tenant = Tenant.query.get(sub.tenant_id)
            if tenant:
                log.info('subscription_expiring', tenant=tenant.slug, days_left=days_left)

        expired = Subscription.query.filter(
            Subscription.end_date < today,
            Subscription.status == 'active'
        ).all()

        for sub in expired:
            sub.status = 'expired'
            tenant = Tenant.query.get(sub.tenant_id)
            if tenant and tenant.status == 'active':
                tenant.status = 'suspended'
                log.info('tenant_suspended_expired', tenant=tenant.slug)

        from app.extensions import db
        db.session.commit()
        return {'expiring_soon': len(expiring_soon), 'expired': len(expired)}


@celery.task(name='app.tasks.helpdesk_tasks.send_overdue_ticket_reminders', bind=True)
def send_overdue_ticket_reminders(self):
    from app import create_app
    from app.models import HelpTicket as HelpDeskTicket, Notification
    from datetime import date, timedelta

    flask_app = create_app()
    with flask_app.app_context():
        from app.extensions import db
        overdue_date = date.today() - timedelta(days=2)
        tickets = HelpDeskTicket.query.filter(
            HelpDeskTicket.status.in_(['open', 'in_progress']),
            HelpDeskTicket.created_at <= overdue_date,
            HelpDeskTicket.is_deleted == False
        ).limit(200).all()

        sent = 0
        for ticket in tickets:
            if ticket.assigned_to_id:
                notif = Notification(
                    tenant_id=ticket.tenant_id,
                    employee_id=ticket.assigned_to_id,
                    type='helpdesk',
                    title=f'⏰ Overdue Ticket: {ticket.title}',
                    body=f'Ticket #{ticket.ticket_number} has been open for more than 2 days.',
                    channel='in_app',
                    reference_type='helpdesk_ticket',
                    reference_id=str(ticket.id)
                )
                db.session.add(notif)
                sent += 1

        db.session.commit()
        log.info('overdue_reminders_sent', count=sent)
        return {'sent': sent}
