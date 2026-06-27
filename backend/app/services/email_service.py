import os
import jinja2
from app.extensions import log

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=jinja2.select_autoescape(["html"]),
)


def render_email(template_name: str, context: dict) -> str:
    """Render a Jinja2 HTML email template. template_name is relative to templates/."""
    try:
        tmpl = _jinja_env.get_template(template_name)
        return tmpl.render(**context)
    except jinja2.TemplateNotFound:
        log.error("email_template_not_found", template=template_name)
        raise


def send_email_template(to: str, subject: str, template_name: str, context: dict) -> bool:
    """Render template and send synchronously. Use queue_email() to send via Celery."""
    from app.utils.notifications import send_email
    if not to:
        return False
    html = render_email(template_name, {**context, "subject": subject})
    plain = _html_to_plain(context)
    return send_email(to, subject, plain, html)


def queue_email(to: str, subject: str, template_name: str, context: dict) -> None:
    """Dispatch email as a background Celery task. Safe to call inside a request."""
    if not to:
        return
    try:
        from app.tasks.notification_tasks import send_template_email
        send_template_email.delay(to, subject, template_name, context)
    except Exception as exc:
        log.error("email_queue_failed", to=to, subject=subject, error=str(exc))
        # Fall back to synchronous send so the email is never silently dropped
        send_email_template(to, subject, template_name, context)


def _html_to_plain(context: dict) -> str:
    """Minimal plain-text fallback — just concatenate visible context values."""
    lines = []
    for k, v in context.items():
        if isinstance(v, str) and v:
            lines.append(f"{k.replace('_', ' ').title()}: {v}")
    return "\n".join(lines)
