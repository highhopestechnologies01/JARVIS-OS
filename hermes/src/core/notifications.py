"""
Notification Dispatcher — sends alerts via multiple channels.

Channels: SMS (Twilio), Email (SMTP), Dashboard (in-memory feed)
"""

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from twilio.rest import Client as TwilioClient

from src.config import settings

log = structlog.get_logger()


class NotificationDispatcher:
    """Sends notifications via configured channels."""

    async def send_sms(
        self,
        message: str,
        to: str | None = None,
    ) -> bool:
        """Send SMS via Twilio."""
        if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from_number]):
            log.warning("notifications.sms.not_configured")
            return False

        to = to or settings.thomas_phone_number
        if not to:
            log.error("notifications.sms.no_recipient")
            return False

        try:
            client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
            msg = client.messages.create(
                body=message,
                from_=settings.twilio_from_number,
                to=to,
            )
            log.info("notifications.sms.sent", sid=msg.sid, to=to)
            return True
        except Exception as e:
            log.error("notifications.sms.failed", error=str(e), to=to)
            return False

    async def send_email(
        self,
        subject: str,
        body: str,
        to: str | None = None,
        html: bool = False,
    ) -> bool:
        """Send email via SMTP."""
        if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password]):
            log.warning("notifications.email.not_configured")
            return False

        to = to or settings.notification_email
        if not to:
            log.error("notifications.email.no_recipient")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_user
            msg["To"] = to

            part = MIMEText(body, "html" if html else "plain")
            msg.attach(part)

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, to, msg.as_string())

            log.info("notifications.email.sent", subject=subject, to=to)
            return True
        except Exception as e:
            log.error("notifications.email.failed", error=str(e), subject=subject)
            return False

    async def send_briefing(self, briefing_content: str, date_str: str) -> dict[str, bool]:
        """Deliver a briefing via all configured channels."""
        results = {}

        # SMS: send summary (first 160 chars)
        sms_preview = f"JARVIS Briefing {date_str}: " + briefing_content[:120] + "..."
        results["sms"] = await self.send_sms(sms_preview)

        # Email: full briefing
        results["email"] = await self.send_email(
            subject=f"JARVIS Executive Briefing — {date_str}",
            body=briefing_content,
        )

        log.info("notifications.briefing.delivered", date=date_str, results=results)
        return results


# Singleton
dispatcher = NotificationDispatcher()
