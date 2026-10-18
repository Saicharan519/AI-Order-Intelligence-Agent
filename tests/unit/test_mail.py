"""The mail sender: which mode MAIL_MODE picks, what the emails say, and that the SMTP
password never appears in an error. No network: the SMTP class is replaced."""

import smtplib

import pytest
from pydantic import SecretStr

from orderintel.api.app import mask_email
from orderintel.auth import mail as m
from orderintel.auth.codes import new_code
from orderintel.config import get_settings

FAKE_PASSWORD = "abcd efgh ijkl mnop"  # noqa: S105  a made-up App Password


def settings(**update):
    return get_settings().model_copy(update=update)


def test_mail_mode_picks_the_sender():
    assert isinstance(m.mailer_for(settings(mail_mode="console")), m.ConsoleMailer)
    assert isinstance(m.mailer_for(settings(mail_mode="SMTP")), m.SmtpMailer)
    assert isinstance(m.mailer_for(settings(mail_mode="off")), m.OffMailer)


def test_console_mode_prints_and_sends_nothing(capsys):
    m.ConsoleMailer().send(m.login_code_mail("a@b.co", "Asha", "123456"))
    err = capsys.readouterr().err
    assert "NOT sent" in err and "123456" in err and "To: a@b.co" in err


def test_off_mode_refuses():
    with pytest.raises(m.MailError):
        m.OffMailer().send(m.Mail("a@b.co", "s", "b"))


def test_smtp_needs_a_user_and_password():
    with pytest.raises(m.MailError, match="SMTP_USER and SMTP_PASSWORD"):
        m.SmtpMailer(settings(smtp_user="", smtp_password=None)).send(m.Mail("a@b.co", "s", "b"))


class FakeSMTP:
    sent: list = []
    fail_login = False

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, f"bad credentials for {password}".encode())
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_smtp_sends_with_tls_and_never_leaks_the_password(monkeypatch):
    monkeypatch.setattr(m.smtplib, "SMTP", FakeSMTP)
    s = settings(smtp_user="me@gmail.com", smtp_password=SecretStr(FAKE_PASSWORD))
    m.SmtpMailer(s).send(m.invite_mail("friend@x.co", "Sai", "http://app/signup?invite=abc"))
    msg = FakeSMTP.sent[-1]
    assert msg["To"] == "friend@x.co" and "me@gmail.com" in msg["From"]
    assert "Sai invited you" in msg["Subject"]

    FakeSMTP.fail_login = True
    with pytest.raises(m.MailError) as e:
        m.SmtpMailer(s).send(m.Mail("friend@x.co", "s", "b"))
    FakeSMTP.fail_login = False
    assert FAKE_PASSWORD not in str(e.value) and "SMTPAuthenticationError" in str(e.value)
    assert FAKE_PASSWORD not in repr(s)


def test_codes_are_six_digits_and_vary():
    codes = {new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150


def test_email_hint_shows_little():
    assert mask_email("k.saicharan@gmail.com") == "k***@gmail.com"
