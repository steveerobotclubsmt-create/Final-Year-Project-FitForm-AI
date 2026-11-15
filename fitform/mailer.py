"""Sends the password-reset codes by email (SMTP over SSL).

The sending account is set up once on the device with tools/setup_email.py, which stores it in
logs/mail.json (not uploaded to GitHub, readable by the owner only). With Gmail this is the address and an
'app password' (Google account -> Security -> 2-Step Verification -> App passwords), never the normal password.
Without that file the phone page says that reset by email is not set up, and tools/reset_password.py on the
device still works."""

import json
import os
import smtplib
import ssl
from email.message import EmailMessage

from . import config

MAIL_FILE = "mail.json"


class Mailer:
    def __init__(self, log_dir=config.LOG_DIR):
        self.path = os.path.join(os.path.abspath(log_dir), MAIL_FILE)

    def settings(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, ValueError):
            return None
        return s if s.get("user") and s.get("app_password") else None

    def configured(self):
        return self.settings() is not None

    def send(self, to, subject, body):
        """Sends one plain-text email. Raises OSError / smtplib.SMTPException when it cannot."""
        s = self.settings()
        if s is None:
            raise OSError("email is not set up (run tools/setup_email.py)")
        msg = EmailMessage()
        msg["From"] = f"{s.get('from_name', 'FitForm AI')} <{s['user']}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP_SSL(s.get("host", "smtp.gmail.com"), int(s.get("port", 465)),
                              context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(s["user"], s["app_password"])
            smtp.send_message(msg)


def save_settings(log_dir, user, app_password, host="smtp.gmail.com", port=465, from_name="FitForm AI"):
    """Writes logs/mail.json readable by the owner only (tools/setup_email.py)."""
    path = os.path.join(os.path.abspath(log_dir), MAIL_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"host": host, "port": port, "user": user, "app_password": app_password,
                   "from_name": from_name}, f, indent=1)
    os.chmod(path, 0o600)
    return path
