import smtplib
import logging
from email.mime.text import MIMEText
from flask import current_app

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    cfg = current_app.config
    host = cfg.get('SMTP_HOST')
    port = cfg.get('SMTP_PORT')
    user = cfg.get('SMTP_USER')
    password = cfg.get('SMTP_PASSWORD')
    mail_from = cfg.get('MAIL_FROM') or user

    if not (host and user and password):
        logger.warning('SMTP not configured — email not sent to %s', to)
        return False

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = mail_from
    msg['To'] = to

    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.login(user, password)
            s.sendmail(mail_from, [to], msg.as_string())
        return True
    except Exception:
        logger.exception('Failed to send email to %s', to)
        return False
