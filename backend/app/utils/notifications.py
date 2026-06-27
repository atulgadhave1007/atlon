import smtplib, ssl, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from app.extensions import log


def send_email(to: str, subject: str, body: str, html: str = None):
    host = current_app.config.get("SMTP_HOST", "")
    port = int(current_app.config.get("SMTP_PORT", 587))
    user = current_app.config.get("SMTP_USER", "")
    pw = current_app.config.get("SMTP_PASS", "")
    from_email = current_app.config.get("FROM_EMAIL", "noreply@atlon.in")
    from_name = current_app.config.get("FROM_NAME", "Atlon HRMS")

    if not host or not user:
        log.warning("SMTP not configured — skipping email", to=to, subject=subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))
    if html:
        msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(user, pw)
            server.sendmail(from_email, to, msg.as_string())
        return True
    except Exception as e:
        log.error("Email send failed", error=str(e), to=to)
        return False


def send_whatsapp(phone: str, message: str):
    token = current_app.config.get("WHATSAPP_TOKEN", "")
    phone_id = current_app.config.get("WHATSAPP_PHONE_ID", "")
    if not token or not phone_id:
        log.warning("WhatsApp not configured", phone=phone)
        return False

    if not phone.startswith("+"):
        phone = f"+91{phone.lstrip('0')}" if len(phone) == 10 else f"+{phone}"

    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace(" ", "").replace("-", ""),
        "type": "text",
        "text": {"body": message},
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error("WhatsApp send failed", error=str(e), phone=phone)
        return False


def notify_leave_event(employee, action: str, leave_type: str, days: float, from_date, to_date):
    subject = f"Leave {action.capitalize()} — {leave_type}"
    body = f"Dear {employee.full_name},\n\nYour {leave_type} leave application for {days} day(s) ({from_date} to {to_date}) has been {action}.\n\nRegards,\nHR Team"
    if employee.work_email:
        send_email(employee.work_email, subject, body)


def notify_payslip_ready(employee, year: int, month: int):
    import calendar
    month_name = calendar.month_name[month]
    subject = f"Your Payslip for {month_name} {year} is Ready"
    body = f"Dear {employee.full_name},\n\nYour payslip for {month_name} {year} is now available. Please log in to Atlon HRMS to view and download it.\n\nRegards,\nHR Team"
    if employee.work_email:
        send_email(employee.work_email, subject, body)
    if employee.personal_phone:
        send_whatsapp(employee.personal_phone, f"Hi {employee.first_name}! Your payslip for {month_name} {year} is ready. Please login to your HRMS portal to download it.")


def notify_birthday(employee):
    subject = "Happy Birthday! 🎂"
    body = f"Dear {employee.full_name},\n\nWishing you a very Happy Birthday from the entire team at Atlon HRMS!\n\nMay this day bring you joy and happiness.\n\nWarm regards,\nHR Team"
    if employee.work_email:
        send_email(employee.work_email, subject, body)
    if employee.personal_phone:
        send_whatsapp(employee.personal_phone, f"Happy Birthday {employee.first_name}! Wishing you a wonderful day filled with joy. 🎉")
