"""Brevo SMTP email sender and LangGraph node wrapper."""
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BREVO_SMTP_HOST = "smtp-relay.brevo.com"
BREVO_SMTP_PORT = 587
DIGEST_RECIPIENT = "dominic@daykanerva.com"


def send_digest_email(html: str) -> None:
    smtp_user = os.environ["BREVO_SMTP_USER"]
    smtp_password = os.environ["BREVO_SMTP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Digest — {date.today().strftime('%B %d, %Y')}"
    msg["From"] = smtp_user
    msg["To"] = DIGEST_RECIPIENT
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)


def send_email_node(state: dict) -> dict:
    """LangGraph node: sends the composed digest and updates state."""
    html = state.get("digest_html", "")
    if html:
        send_digest_email(html)
    return {"email_sent": bool(html)}
