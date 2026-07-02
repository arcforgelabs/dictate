"""SMTP delivery for Dictate Pro sign-in codes."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class AuthDeliveryError(Exception):
    """Sign-in code could not be delivered."""


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    from_address: str
    use_tls: bool
    timeout: float


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_smtp_settings() -> SmtpSettings | None:
    host = os.environ.get("DICTATE_PRO_SMTP_HOST", "").strip()
    if not host:
        return None
    port = int(os.environ.get("DICTATE_PRO_SMTP_PORT", "587"))
    username = os.environ.get("DICTATE_PRO_SMTP_USERNAME", "").strip() or None
    password = os.environ.get("DICTATE_PRO_SMTP_PASSWORD", "").strip() or None
    from_address = os.environ.get("DICTATE_PRO_SMTP_FROM", "").strip()
    if not from_address and username:
        from_address = username
    if not from_address:
        raise AuthDeliveryError("DICTATE_PRO_SMTP_FROM is required when SMTP is configured")
    use_tls = _env_bool("DICTATE_PRO_SMTP_TLS", default=True)
    timeout = float(os.environ.get("DICTATE_PRO_SMTP_TIMEOUT", "10"))
    return SmtpSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        from_address=from_address,
        use_tls=use_tls,
        timeout=timeout,
    )


def send_auth_code(*, to_address: str, code: str, settings: SmtpSettings | None = None) -> None:
    smtp_settings = settings if settings is not None else load_smtp_settings()
    if smtp_settings is None:
        raise AuthDeliveryError("sign-in code delivery is not configured")

    message = EmailMessage()
    message["Subject"] = "Your Dictate Pro sign-in code"
    message["From"] = smtp_settings.from_address
    message["To"] = to_address
    message.set_content(
        "Your Dictate Pro sign-in code is:\n\n"
        f"{code}\n\n"
        "This code expires in 10 minutes. If you did not request it, you can ignore this email."
    )

    try:
        with smtplib.SMTP(
            smtp_settings.host,
            smtp_settings.port,
            timeout=smtp_settings.timeout,
        ) as smtp:
            if smtp_settings.use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if smtp_settings.username:
                smtp.login(
                    smtp_settings.username,
                    smtp_settings.password or "",
                )
            smtp.send_message(message)
    except AuthDeliveryError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to deliver sign-in code via SMTP to %s: %s",
            to_address,
            exc.__class__.__name__,
        )
        raise AuthDeliveryError("failed to deliver sign-in code") from exc
