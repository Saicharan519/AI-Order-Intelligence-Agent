"""Emailed 6-digit codes: sign-in, trusted devices, password reset, email change, invites.

Real database, emails kept in memory (MemoryMailer; nothing is sent). Accounts use the
domain accounts.test and are deleted at the end, with their codes and devices (cascade).
"""

import re

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from orderintel.agent.session import SessionStore
from orderintel.api.app import create_app
from orderintel.auth.codes import MAX_CODES_PER_HOUR, CodeStore
from orderintel.auth.crypto import new_token, token_hash
from orderintel.auth.mail import MemoryMailer
from orderintel.auth.store import AccountError, AccountStore
from orderintel.config import get_settings
from orderintel.db.connect import connect_agent, connect_owner
from orderintel.trace.recorder import TraceRecorder

pytestmark = pytest.mark.integration

try:
    with connect_agent() as _c:
        _c.execute("SELECT 1 FROM analytics.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

PW = "a good passphrase 1"
NEW_PW = "another good passphrase 2"
APP_URL = "http://app.test"


def make(mailer: MemoryMailer | None = None) -> tuple[TestClient, MemoryMailer]:
    s = get_settings().model_copy(
        update={
            "access_code": SecretStr("operator-key-for-tests"),
            "login_code_required": True,
            "app_url": APP_URL,
        }
    )
    mailer = mailer or MemoryMailer()
    app = create_app(
        s,
        recorder=TraceRecorder(s),
        store=SessionStore(),
        trace_config="test:codes",
        accounts=AccountStore(s),
        mailer=mailer,
    )
    return TestClient(app, raise_server_exceptions=False), mailer


@pytest.fixture(autouse=True, scope="module")
def cleanup():
    yield
    with connect_owner() as conn:
        conn.execute("DELETE FROM app.invites WHERE email LIKE '%%@accounts.test'")
        conn.execute(
            "DELETE FROM app.sessions WHERE user_id IN "
            "(SELECT id FROM app.users WHERE email LIKE '%%@accounts.test')"
        )
        conn.execute("DELETE FROM app.users WHERE email LIKE '%%@accounts.test'")


_n = [0]


def unique(prefix: str) -> str:
    _n[0] += 1
    return f"{prefix}{_n[0]}-{id(_n)}@accounts.test"


@pytest.fixture
def person():
    email = unique("code")
    AccountStore().create_user(email, "Asha", PW, role="admin")
    return email


def code_in(mailer: MemoryMailer, to: str) -> str:
    mail = [m for m in mailer.sent if m.to == to][-1]
    return re.search(r"\b(\d{6})\b", mail.body).group(1)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def start_login(c: TestClient, email: str, password: str = PW, device: str = "") -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": password, "device": device})
    assert r.status_code == 200, r.json()
    return r.json()


def full_sign_in(c, mailer, email, password=PW, trust=False) -> dict:
    challenge = start_login(c, email, password)["challenge"]
    r = c.post(
        "/v1/auth/login/verify",
        json={"challenge": challenge, "code": code_in(mailer, email), "trust_device": trust},
    )
    assert r.status_code == 200, r.json()
    return r.json()


def age_codes(email: str, seconds: int) -> None:
    """Pretend the user's codes were sent some seconds ago."""
    with connect_owner() as conn:
        conn.execute(
            "UPDATE app.email_codes SET last_sent_at = last_sent_at - make_interval(secs => %s) "
            "WHERE user_id = (SELECT id FROM app.users WHERE email = %s)",
            (seconds, email),
        )


# ---------- sign-in ----------


def test_the_password_alone_gives_no_session_only_an_emailed_code(person):
    c, mailer = make()
    body = start_login(c, person)
    assert body["code_required"] is True and "token" not in body
    assert body["email_hint"].startswith(person[0] + "***@")
    mail = mailer.sent[-1]
    assert mail.to == person and "http" not in mail.body  # a code email carries no link
    code = code_in(mailer, person)
    assert code in mail.subject

    r = c.post("/v1/auth/login/verify", json={"challenge": body["challenge"], "code": code})
    assert r.status_code == 200 and r.json()["user"]["email"] == person
    assert c.get("/v1/auth/me", headers=bearer(r.json()["token"])).status_code == 200
    again = c.post("/v1/auth/login/verify", json={"challenge": body["challenge"], "code": code})
    assert again.status_code == 400 and again.json()["error"]["code"] == "wrong_code"  # once


def test_a_wrong_password_sends_no_email(person):
    c, mailer = make()
    r = c.post("/v1/auth/login", json={"email": person, "password": "not the password"})
    assert r.status_code == 401 and mailer.sent == []


def test_five_wrong_codes_end_the_code_even_for_the_right_one_after(person):
    c, mailer = make()
    challenge = start_login(c, person)["challenge"]
    right = code_in(mailer, person)
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        r = c.post("/v1/auth/login/verify", json={"challenge": challenge, "code": wrong})
        assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_code"
    r = c.post("/v1/auth/login/verify", json={"challenge": challenge, "code": right})
    assert r.status_code == 400


def test_a_code_belongs_to_its_own_challenge(person):
    c, mailer = make()
    start_login(c, person)
    code = code_in(mailer, person)
    other = start_login(c, person)["challenge"]  # a second browser waiting for its own code
    other_code = code_in(mailer, person)
    if other_code != code:
        r = c.post("/v1/auth/login/verify", json={"challenge": other, "code": code})
        assert r.status_code == 400
    made_up = c.post("/v1/auth/login/verify", json={"challenge": new_token(), "code": code})
    assert made_up.status_code == 400


def test_an_expired_code_is_refused(person):
    c, mailer = make()
    challenge = start_login(c, person)["challenge"]
    with connect_owner() as conn:
        conn.execute(
            "UPDATE app.email_codes SET expires_at = now() - interval '1 second' "
            "WHERE secret_hash = %s",
            (token_hash(challenge),),
        )
    r = c.post(
        "/v1/auth/login/verify", json={"challenge": challenge, "code": code_in(mailer, person)}
    )
    assert r.status_code == 400


def test_resend_waits_a_minute_and_replaces_the_code(person):
    c, mailer = make()
    challenge = start_login(c, person)["challenge"]
    first = code_in(mailer, person)
    r = c.post("/v1/auth/login/resend", json={"challenge": challenge})
    assert r.status_code == 429 and r.json()["error"]["code"] == "resend_wait"
    age_codes(person, 61)
    assert c.post("/v1/auth/login/resend", json={"challenge": challenge}).status_code == 200
    second = code_in(mailer, person)
    if second != first:
        r = c.post("/v1/auth/login/verify", json={"challenge": challenge, "code": first})
        assert r.status_code == 400
    r = c.post("/v1/auth/login/verify", json={"challenge": challenge, "code": second})
    assert r.status_code == 200


def test_codes_and_challenges_are_stored_only_as_hashes(person):
    c, mailer = make()
    challenge = start_login(c, person)["challenge"]
    code = code_in(mailer, person)
    with connect_owner() as conn:
        rows = conn.execute(
            "SELECT secret_hash, code_hash FROM app.email_codes WHERE user_id = "
            "(SELECT id FROM app.users WHERE email = %s)",
            (person,),
        ).fetchall()
    assert rows and rows[0][0] == token_hash(challenge)
    dump = repr(rows)
    assert challenge not in dump and code not in dump


def test_the_mail_failing_is_reported_and_gives_no_session(person):
    c, _ = make(MemoryMailer(fail=True))
    r = c.post("/v1/auth/login", json={"email": person, "password": PW})
    assert r.status_code == 502 and r.json()["error"]["code"] == "mail_failed"


def test_too_many_codes_in_an_hour_are_refused(person):
    user = AccountStore().user_by_email(person)
    store = CodeStore()
    for _ in range(MAX_CODES_PER_HOUR):
        store.start(user.id, "login", new_token())
    with pytest.raises(AccountError) as e:
        store.start(user.id, "login", new_token())
    assert e.value.code == "too_many_codes"


# ---------- trusted devices ----------


def test_a_trusted_device_skips_the_code_for_that_user_only(person):
    c, mailer = make()
    device = full_sign_in(c, mailer, person, trust=True)["device_token"]
    body = start_login(c, person, device=device)
    assert "token" in body and "code_required" not in body

    other = unique("other")
    AccountStore().create_user(other, "Ravi", PW)
    assert start_login(c, other, device=device)["code_required"] is True
    assert start_login(c, person, device=new_token())["code_required"] is True


def test_changing_the_password_untrusts_every_device(person):
    c, mailer = make()
    signed = full_sign_in(c, mailer, person, trust=True)
    r = c.post(
        "/v1/account/password",
        json={"current_password": PW, "new_password": NEW_PW},
        headers=bearer(signed["token"]),
    )
    assert r.status_code == 200
    assert start_login(c, person, NEW_PW, device=signed["device_token"])["code_required"] is True


# ---------- forgot password ----------


def test_forgot_password_answers_the_same_for_unknown_emails(person):
    c, mailer = make()
    known = c.post("/v1/auth/password/forgot", json={"email": person})
    unknown = c.post("/v1/auth/password/forgot", json={"email": unique("nobody")})
    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json())
    assert [m.to for m in mailer.sent] == [person]  # only a real account gets an email
    r = c.post(
        "/v1/auth/password/reset",
        json={"challenge": unknown.json()["challenge"], "code": "123456", "new_password": NEW_PW},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_code"


def test_reset_sets_the_new_password_and_ends_every_session(person):
    c, mailer = make()
    old_session = full_sign_in(c, mailer, person, trust=True)
    challenge = c.post("/v1/auth/password/forgot", json={"email": person}).json()["challenge"]
    code = code_in(mailer, person)
    weak = c.post(
        "/v1/auth/password/reset",
        json={"challenge": challenge, "code": code, "new_password": "short"},
    )
    assert weak.status_code == 400 and weak.json()["error"]["code"] == "weak_password"
    r = c.post(
        "/v1/auth/password/reset",
        json={"challenge": challenge, "code": code, "new_password": NEW_PW},
    )  # the weak attempt did not use up the code
    assert r.status_code == 200
    assert c.get("/v1/auth/me", headers=bearer(old_session["token"])).status_code == 401
    assert c.post("/v1/auth/login", json={"email": person, "password": PW}).status_code == 401
    body = start_login(c, person, NEW_PW, device=old_session["device_token"])
    assert body["code_required"] is True  # the device is no longer trusted


def test_password_resend_never_reveals_anything(person):
    c, _ = make()
    r = c.post("/v1/auth/password/resend", json={"challenge": new_token()})
    assert r.status_code == 200 and r.json() == {"ok": True}


# ---------- email change ----------


def test_a_new_email_is_used_only_after_its_code(person):
    c, mailer = make()
    token = full_sign_in(c, mailer, person)["token"]
    new = unique("moved")
    r = c.post(
        "/v1/account/profile",
        json={"name": "Asha", "email": new, "current_password": PW},
        headers=bearer(token),
    )
    assert r.status_code == 200 and r.json()["pending_email"] == new
    assert mailer.sent[-1].to == new  # the code goes to the NEW address
    code = code_in(mailer, new)

    wrong = "000000" if code != "000000" else "111111"
    r = c.post("/v1/account/email/confirm", json={"code": wrong}, headers=bearer(token))
    assert r.status_code == 400
    other_session = full_sign_in(c, mailer, person)["token"]
    r = c.post("/v1/account/email/confirm", json={"code": code}, headers=bearer(other_session))
    assert r.status_code == 400  # the code belongs to the session that asked for it

    r = c.post("/v1/account/email/confirm", json={"code": code}, headers=bearer(token))
    assert r.status_code == 200 and r.json()["email"] == new
    assert c.get("/v1/auth/me", headers=bearer(token)).json()["email"] == new


def test_an_email_change_to_a_taken_address_sends_nothing(person):
    c, mailer = make()
    token = full_sign_in(c, mailer, person)["token"]
    taken = unique("taken")
    AccountStore().create_user(taken, "Ravi", PW)
    before = len(mailer.sent)
    r = c.post(
        "/v1/account/profile",
        json={"name": "Asha", "email": taken, "current_password": PW},
        headers=bearer(token),
    )
    assert r.status_code == 409 and len(mailer.sent) == before


# ---------- invites ----------


def test_an_invite_is_emailed_with_its_link(person):
    c, mailer = make()
    token = full_sign_in(c, mailer, person)["token"]
    friend = unique("friend")
    r = c.post("/v1/admin/invites", json={"email": friend}, headers=bearer(token))
    assert r.status_code == 200 and r.json()["mail"] == {"sent": True, "mode": "memory"}
    mail = mailer.sent[-1]
    assert mail.to == friend and "Asha invited you" in mail.subject
    assert f"{APP_URL}/signup?invite={r.json()['code']}" in mail.body


def test_an_invite_still_works_when_the_email_fails(person):
    c, mailer = make()
    token = full_sign_in(c, mailer, person)["token"]
    mailer.fail = True
    r = c.post("/v1/admin/invites", json={"email": unique("friend")}, headers=bearer(token))
    assert r.status_code == 200 and r.json()["mail"]["sent"] is False
    assert r.json()["code"]  # the admin can still copy the link
