"""
Email agent — sends a formatted HTML report to a given recipient.
recipient_email is now passed at call time instead of being hardcoded.
"""

import os
from typing import Dict

import sendgrid
from sendgrid.helpers.mail import Email, Mail, Content, To
from agents import Agent, function_tool


def make_email_agent(recipient_email: str):
    """
    Factory that returns an email agent wired to the given recipient.
    Call this per-request so each user gets their own email.
    """

    @function_tool
    def send_email(subject: str, html_body: str) -> Dict[str, str]:
        """Send an email with the given subject and HTML body."""
        sg = sendgrid.SendGridAPIClient(api_key=os.environ.get("SENDGRID_API_KEY"))
        from_email = Email(os.environ.get("SENDER_EMAIL_SENDGRID", ""))
        to_email   = To(recipient_email)
        content    = Content("text/html", html_body)
        mail       = Mail(from_email, to_email, subject, content).get()
        response   = sg.client.mail.send.post(request_body=mail)
        print(f"Email → {recipient_email} | status {response.status_code}")
        return {"status": "success", "recipient": recipient_email}

    return Agent(
        name="Email agent",
        instructions=(
            "You are able to send a nicely formatted HTML email based on a detailed report. "
            "You will be provided with a detailed report. Send one email, converting the report "
            "into clean, well-presented HTML with an appropriate subject line."
        ),
        tools=[send_email],
        model="gpt-4o-mini",
    )


# ── Backwards-compat singleton (uses env var fallback) ────────────────────
email_agent = make_email_agent(
    os.environ.get("RECIPIENT_EMAIL", "")
)
