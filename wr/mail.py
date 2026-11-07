"""Deliver the report. Methods: "smtp" (any SMTP server), "command" (your own command) or "none" (files only)."""

from __future__ import annotations

import os
import smtplib
import ssl
import subprocess
import tempfile
from email.message import EmailMessage
from pathlib import Path

from .config import Settings


class MailError(RuntimeError):
    pass


def _run_shell(cmd: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env={**os.environ, **(env or {})})


def password(cfg: dict) -> str:
    """SMTP password from (in order) password_command, the env variable, or the optional `keyring` package."""
    if cfg.get("password_command"):
        r = _run_shell(cfg["password_command"], timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        raise MailError(f"password_command failed: {(r.stderr or 'no output').strip()[:200]}")
    env_name = cfg.get("password_env", "WEEKLY_REVIEW_SMTP_PASSWORD")
    if os.environ.get(env_name):
        return os.environ[env_name]
    try:
        import keyring  # optional third-party package
        value = keyring.get_password(cfg.get("keyring_service", "weekly-review"), cfg.get("username", ""))
        if value:
            return value
    except ImportError:
        pass
    raise MailError(
        f"No SMTP password. Set the environment variable {env_name}, or set mail.password_command, "
        "or store it with the Python keyring package. See references/mail.md."
    )


def _smtp(cfg: dict) -> smtplib.SMTP:
    host, port = cfg.get("smtp_host", ""), int(cfg.get("smtp_port", 465))
    if not host:
        raise MailError("mail.smtp_host is not set")
    context = ssl.create_default_context()
    if cfg.get("smtp_security", "ssl") == "ssl":
        conn = smtplib.SMTP_SSL(host, port, context=context, timeout=60)
    else:
        conn = smtplib.SMTP(host, port, timeout=60)
        conn.starttls(context=context)
    secret = password(cfg)
    if cfg.get("strip_spaces", False):  # some providers show app passwords in groups of four letters
        secret = secret.replace(" ", "")
    try:
        conn.login(cfg.get("username", ""), secret)
    except smtplib.SMTPAuthenticationError as exc:
        conn.close()
        raise MailError(f"The SMTP server refused the login: {exc.smtp_error!r}") from exc
    except Exception:
        conn.close()
        raise
    return conn


def send(settings: Settings, subject: str, html: str, text: str) -> str:
    cfg = settings.mail
    method = cfg.get("method", "none")
    if method == "none":
        return "mail.method is 'none': the report is only written to the out folder"
    if method == "command":
        with tempfile.TemporaryDirectory() as tmp:
            html_file, text_file = Path(tmp) / "report.html", Path(tmp) / "report.txt"
            html_file.write_text(html, encoding="utf-8")
            text_file.write_text(text, encoding="utf-8")
            env = {"WR_TO": settings.to, "WR_SUBJECT": subject, "WR_HTML_FILE": str(html_file), "WR_TEXT_FILE": str(text_file)}
            r = _run_shell(cfg["command"], env=env, timeout=300)
        if r.returncode != 0:
            raise MailError(f"mail.command failed: {(r.stderr or r.stdout).strip()[:500]}")
        return "sent with mail.command"
    if method == "smtp":
        msg = EmailMessage()
        msg["From"] = cfg.get("from") or cfg.get("username", "")
        msg["To"] = settings.to
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        with _smtp(cfg) as conn:
            conn.send_message(msg)
        return f"sent with SMTP ({cfg.get('smtp_host')})"
    raise MailError(f"Unknown mail.method {method!r}; use smtp, command or none")


def check(settings: Settings) -> str:
    """Prove that sending will work, without sending."""
    cfg = settings.mail
    method = cfg.get("method", "none")
    if method == "smtp":
        with _smtp(cfg):
            pass
        return f"SMTP login to {cfg.get('smtp_host')} works"
    if method == "command":
        if not cfg.get("command"):
            raise MailError("mail.command is empty")
        return "mail.command is set (not run by check)"
    return "mail.method is 'none' (no email; reports are files only)"
