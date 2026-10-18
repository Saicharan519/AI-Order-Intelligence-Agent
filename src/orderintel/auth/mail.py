"""Sending email: sign-in codes, password reset codes, email-change codes and invites.

MAIL_MODE picks how:
- console: print the email in the API's terminal instead of sending it (development; the
  code is visible only to whoever runs the API);
- smtp: send it through a mail server, for example Gmail (smtp.gmail.com, port 587,
  SMTP_USER = the Gmail address, SMTP_PASSWORD = a Google App Password, never the real
  Gmail password);
- off: send nothing.

Emails are plain text with no tracking and, for codes, no links (a code email with a link
looks like phishing). Email bodies never pass through the logs.
"""

from __future__ import annotations

import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from orderintel.config import Settings


class MailError(Exception):
    """The email could not be sent (wrong settings, server down, ...)."""


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class Mailer:
    mode = "base"

    def send(self, mail: Mail) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleMailer(Mailer):
    mode = "console"

    def send(self, mail: Mail) -> None:
        line = "=" * 64
        print(
            f"\n{line}\n[mail, console mode: NOT sent]\nTo: {mail.to}\nSubject: {mail.subject}\n\n"
            f"{mail.body}\n{line}\n",
            file=sys.stderr,
            flush=True,
        )


class OffMailer(Mailer):
    mode = "off"

    def send(self, mail: Mail) -> None:
        raise MailError("Email is turned off (MAIL_MODE=off).")


class SmtpMailer(Mailer):
    mode = "smtp"

    def __init__(self, s: Settings) -> None:
        self.host, self.port, self.user = s.smtp_host, s.smtp_port, s.smtp_user
        self._password = s.smtp_password
        self.from_name = s.mail_from_name

    def send(self, mail: Mail) -> None:
        if not self.user or self._password is None:
            raise MailError("SMTP_USER and SMTP_PASSWORD must be set for MAIL_MODE=smtp.")
        msg = EmailMessage()
        msg["From"] = formataddr((self.from_name, self.user))
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg["Message-ID"] = make_msgid(domain=self.user.split("@")[-1])
        msg.set_content(mail.body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.user, self._password.get_secret_value())
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            # The exception type only: server messages can echo the address or settings.
            raise MailError(f"Sending failed ({type(e).__name__}).") from None


@dataclass
class MemoryMailer(Mailer):
    """For tests: keeps the emails in a list."""

    mode = "memory"
    sent: list[Mail] = field(default_factory=list)
    fail: bool = False

    def send(self, mail: Mail) -> None:
        if self.fail:
            raise MailError("Sending failed (test).")
        self.sent.append(mail)


def mailer_for(s: Settings) -> Mailer:
    mode = (s.mail_mode or "console").strip().lower()
    if mode == "smtp":
        return SmtpMailer(s)
    if mode == "off":
        return OffMailer()
    return ConsoleMailer()


# ---------- the emails ----------

SIGN = "\n\nIf this wasn't you, you can ignore this email.\n\nOrder Intelligence"


def login_code_mail(to: str, name: str, code: str) -> Mail:
    return Mail(
        to,
        f"{code} is your Order Intelligence sign-in code",
        f"Hi {name},\n\nYour sign-in code is:\n\n    {code}\n\n"
        "It works once and expires in 10 minutes. Never share it: we will never ask you "
        "for it." + SIGN,
    )


def reset_code_mail(to: str, name: str, code: str) -> Mail:
    return Mail(
        to,
        f"{code} is your Order Intelligence password reset code",
        f"Hi {name},\n\nSomeone asked to reset the password of your account. Your code is:\n\n"
        f"    {code}\n\nIt works once and expires in 10 minutes." + SIGN,
    )


def email_change_mail(to: str, name: str, code: str) -> Mail:
    return Mail(
        to,
        f"{code} is your code to confirm this email address",
        f"Hi {name},\n\nTo use this address for your Order Intelligence account, enter:\n\n"
        f"    {code}\n\nIt works once and expires in 10 minutes." + SIGN,
    )


def invite_mail(to: str, inviter: str, link: str) -> Mail:
    return Mail(
        to,
        f"{inviter} invited you to Order Intelligence",
        f"Hi,\n\n{inviter} invited you to Order Intelligence, an analytics assistant that "
        "answers questions about e-commerce orders in plain English.\n\n"
        f"Create your account here (you choose your own name and password):\n\n{link}\n\n"
        "The link works once and expires in 7 days.\n\nOrder Intelligence",
    )
