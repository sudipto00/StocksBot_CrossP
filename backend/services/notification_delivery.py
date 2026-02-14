"""
Notification delivery service.
Provides concrete email/SMS transport implementations for summary notifications.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from config.settings import get_settings
from api.models import SummaryNotificationChannel


class NotificationDeliveryService:
    """Dispatches summary notifications over configured delivery channels."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def send_summary(
        self,
        channel: SummaryNotificationChannel,
        recipient: str,
        subject: str,
        body: str,
    ) -> str:
        """Send summary notification using selected channel."""
        if not self.settings.summary_notifications_enabled:
            raise RuntimeError("Summary notification transport is disabled by configuration")

        if channel == SummaryNotificationChannel.EMAIL:
            self._send_email(recipient=recipient, subject=subject, body=body)
            return f"Email sent to {recipient}"

        if channel == SummaryNotificationChannel.SMS:
            self._send_sms_twilio(recipient=recipient, body=body)
            return f"SMS sent to {recipient}"

        raise RuntimeError(f"Unsupported notification channel: {channel}")

    def _send_email(self, recipient: str, subject: str, body: str) -> None:
        """Send summary via SMTP."""
        smtp_host = (self.settings.smtp_host or "").strip()
        smtp_username = (self.settings.smtp_username or "").strip()
        smtp_password = (self.settings.smtp_password or "").strip()
        from_email = (self.settings.smtp_from_email or "").strip()

        if not smtp_host:
            raise RuntimeError("SMTP host is not configured (STOCKSBOT_SMTP_HOST)")
        if not from_email:
            raise RuntimeError("SMTP from address is not configured (STOCKSBOT_SMTP_FROM_EMAIL)")
        if not smtp_username or not smtp_password:
            raise RuntimeError("SMTP credentials are not configured (STOCKSBOT_SMTP_USERNAME/PASSWORD)")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = from_email
        message["To"] = recipient
        message.set_content(body)

        timeout = max(1, int(self.settings.smtp_timeout_seconds))
        port = int(self.settings.smtp_port)
        use_ssl = bool(self.settings.smtp_use_ssl)
        use_tls = bool(self.settings.smtp_use_tls)

        smtp_client: Optional[smtplib.SMTP] = None
        try:
            if use_ssl:
                smtp_client = smtplib.SMTP_SSL(smtp_host, port, timeout=timeout)
            else:
                smtp_client = smtplib.SMTP(smtp_host, port, timeout=timeout)
            smtp_client.ehlo()
            if (not use_ssl) and use_tls:
                smtp_client.starttls()
                smtp_client.ehlo()
            smtp_client.login(smtp_username, smtp_password)
            smtp_client.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise RuntimeError(f"SMTP delivery failed: {exc}") from exc
        finally:
            if smtp_client is not None:
                try:
                    smtp_client.quit()
                except (smtplib.SMTPException, OSError):
                    pass

    def _send_sms_twilio(self, recipient: str, body: str) -> None:
        """Send summary via Twilio REST API."""
        sid = (self.settings.twilio_account_sid or "").strip()
        token = (self.settings.twilio_auth_token or "").strip()
        from_number = (self.settings.twilio_from_number or "").strip()

        if not sid:
            raise RuntimeError("Twilio account SID is not configured (STOCKSBOT_TWILIO_ACCOUNT_SID)")
        if not token:
            raise RuntimeError("Twilio auth token is not configured (STOCKSBOT_TWILIO_AUTH_TOKEN)")
        if not from_number:
            raise RuntimeError("Twilio from number is not configured (STOCKSBOT_TWILIO_FROM_NUMBER)")

        timeout = max(1, int(self.settings.twilio_timeout_seconds))
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        payload = {"To": recipient, "From": from_number, "Body": body}
        try:
            response = httpx.post(url, data=payload, auth=(sid, token), timeout=timeout)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Twilio request failed: {exc}") from exc

        if response.status_code < 200 or response.status_code >= 300:
            detail = response.text.strip()
            if len(detail) > 280:
                detail = detail[:280]
            raise RuntimeError(f"Twilio delivery failed ({response.status_code}): {detail}")
