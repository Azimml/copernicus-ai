"""SMTP email sending for operator replies to support requests.

Configure via SMTP_* env vars in .env. If SMTP_HOST is blank the service
returns a "disabled" status without raising — useful for local dev or for
deployments that haven't picked an email provider yet.

Designed to be drop-in compatible with Gmail SMTP, Mailgun, SendGrid SMTP,
Postmark, AWS SES, and any standard SMTP server.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EmailResult:
    ok: bool
    error: str = ""
    skipped: bool = False  # True when SMTP is intentionally disabled


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_operator_reply(
    *,
    to_email: str,
    to_name: str,
    operator_name: str,
    original_question: str,
    reply_body: str,
) -> EmailResult:
    """Send an operator's reply to a support-form submitter.

    Returns an :class:`EmailResult` rather than raising — callers want to
    record the outcome alongside the reply in the handoff log.
    """
    if not is_configured():
        logger.warning("SMTP not configured; skipping email to %s", to_email)
        return EmailResult(ok=False, skipped=True, error="SMTP not configured")

    if not to_email or "@" not in to_email:
        return EmailResult(ok=False, error=f"Invalid recipient address: {to_email!r}")

    subject_q = (original_question or "").strip().splitlines()[0][:80] or "your question"
    subject = f"Re: {subject_q} — Copernicus Berlin"

    plain = (
        f"Hi {to_name or 'there'},\n\n"
        f"Thank you for reaching out to Copernicus Berlin. Here is our reply to your question:\n\n"
        f"> {original_question.strip()}\n\n"
        f"{reply_body.strip()}\n\n"
        f"Kind regards,\n"
        f"{operator_name}\n"
        f"Copernicus Berlin e. V.\n"
    )

    html = _render_html(
        to_name=to_name or "there",
        operator_name=operator_name,
        original_question=original_question.strip(),
        reply_body=reply_body.strip(),
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.smtp_from_name or "Copernicus Berlin", settings.smtp_from))
    msg["To"] = formataddr((to_name or "", to_email))
    if settings.smtp_reply_to:
        msg["Reply-To"] = settings.smtp_reply_to
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.rsplit("@", 1)[-1])
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    try:
        if settings.smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ctx) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                s.ehlo()
                if settings.smtp_use_tls:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        logger.info("Sent operator reply to %s", to_email)
        return EmailResult(ok=True)
    except Exception as exc:
        logger.exception("Failed to send operator reply to %s", to_email)
        return EmailResult(ok=False, error=str(exc)[:300])


def _render_html(*, to_name: str, operator_name: str, original_question: str, reply_body: str) -> str:
    """Minimal HTML email template. Inline styles, no external assets — works
    in Gmail, Outlook, Apple Mail without rendering quirks."""
    import html as html_lib
    q = html_lib.escape(original_question).replace("\n", "<br>")
    body = html_lib.escape(reply_body).replace("\n", "<br>")
    name = html_lib.escape(to_name)
    op = html_lib.escape(operator_name)
    return f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f8fc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#111827;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f6f8fc;padding:24px 0;">
  <tr><td align="center">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 14px rgba(10,37,64,.06);">
      <tr><td style="background:linear-gradient(135deg,#0a2540,#1d3a72);padding:20px 28px;color:#fff;">
        <div style="font-weight:600;font-size:18px;line-height:1.2;">Copernicus Berlin</div>
        <div style="font-size:13px;opacity:.85;">A reply to your enquiry</div>
      </td></tr>
      <tr><td style="padding:24px 28px 8px;">
        <p style="margin:0 0 12px;font-size:15px;">Hi {name},</p>
        <p style="margin:0 0 16px;font-size:14px;color:#374151;line-height:1.55;">
          Thank you for reaching out to <b>Copernicus Berlin</b>. Here is our reply to your question:
        </p>
        <div style="background:#f6f8fc;border-left:3px solid #ee7625;padding:12px 14px;border-radius:0 8px 8px 0;font-size:13.5px;color:#374151;line-height:1.55;margin:0 0 18px;">
          {q}
        </div>
        <div style="font-size:14.5px;line-height:1.6;color:#111827;white-space:pre-wrap;">{body}</div>
      </td></tr>
      <tr><td style="padding:18px 28px 28px;color:#6b7280;font-size:13px;line-height:1.5;">
        Kind regards,<br>
        <b style="color:#0a2540;">{op}</b><br>
        Copernicus Berlin e. V.
      </td></tr>
    </table>
    <div style="font-size:11px;color:#9ca3af;margin-top:14px;">
      This is an automated reply from the Copernicus Berlin support inbox. Reply to this email to continue the conversation.
    </div>
  </td></tr>
</table>
</body></html>"""
