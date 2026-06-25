import os
import requests

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def send_mail(subject, recipients, body):
    """Send email via the SendGrid HTTPS API.

    Uses port 443 instead of SMTP (587/465), which DigitalOcean blocks
    outbound by default on new droplets/accounts.
    """
    api_key = os.getenv('mail_password')
    sender = os.getenv('mail_sender')
    payload = {
        "personalizations": [{"to": [{"email": r} for r in recipients]}],
        "from": {"email": sender},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    resp = requests.post(
        SENDGRID_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
