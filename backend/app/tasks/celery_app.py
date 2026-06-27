from celery import Celery
from celery.schedules import crontab
import os


def make_celery():
    broker = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    backend = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    app = Celery('atlon_hrms', broker=broker, backend=backend)

    app.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        beat_schedule={
            'accrue-leave-monthly': {
                'task': 'app.tasks.leave_tasks.accrue_leave_all_tenants',
                'schedule': crontab(day_of_month=1, hour=0, minute=5),
            },
            'birthday-notifications-daily': {
                'task': 'app.tasks.notification_tasks.send_birthday_notifications',
                'schedule': crontab(hour=8, minute=0),
            },
            'work-anniversary-daily': {
                'task': 'app.tasks.notification_tasks.send_anniversary_notifications',
                'schedule': crontab(hour=8, minute=30),
            },
            'attendance-absent-mark': {
                'task': 'app.tasks.attendance_tasks.mark_absent_for_previous_day',
                'schedule': crontab(hour=1, minute=0),
            },
            'leave-expiry-check': {
                'task': 'app.tasks.leave_tasks.expire_leave_balances',
                'schedule': crontab(hour=0, minute=30),
            },
            'subscription-expiry-check': {
                'task': 'app.tasks.billing_tasks.check_subscription_expiry',
                'schedule': crontab(hour=2, minute=0),
            },
            'pending-ticket-reminder': {
                'task': 'app.tasks.helpdesk_tasks.send_overdue_ticket_reminders',
                'schedule': crontab(hour=10, minute=0),
            },
        }
    )
    return app


celery = make_celery()
