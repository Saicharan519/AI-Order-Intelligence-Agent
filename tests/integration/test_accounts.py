"""Accounts: invite-only sign-up, sign-in, sessions, admin, and per-user privacy and limits.

Real database, fake model (billed at $0 under the Gemini fake config). Every account uses
the domain accounts.test and every trace row the tag test:acct; both are deleted at the end.
"""

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from orderintel.agent.session import SessionStore
from orderintel.api.app import create_app
from orderintel.auth.crypto import token_hash
from orderintel.auth.mail import MemoryMailer
from orderintel.auth.store import AccountStore
from orderintel.config import get_settings
from orderintel.db.connect import connect_agent, connect_owner, connect_trace
from orderintel.llm.budget import PostgresLedger
from orderintel.llm.client import LLMClient
from orderintel.trace.recorder import TraceRecorder
from tests.fixtures.fake_llm import fake_config
from tests.integration.test_ask_fake import CANCELED_SQL, ROUTE_ANSWER, RoleFake

pytestmark = pytest.mark.integration

try:
    with connect_agent() as _c:
        _c.execute("SELECT 1 FROM analytics.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

TAG = "test:acct"
CODE = "operator-key-for-tests"  # a made-up operator key, not the project's ACCESS_CODE
PW = "a good passphrase 1"


def settings(**update):
    # Sign-in codes are tested in test_email_codes.py; here a password alone signs in.
    base = {
        "access_code": SecretStr(CODE),
        "rate_limit_per_ip_per_min": 50,
        "login_code_required": False,
    }
    return get_settings().model_copy(update={**base, **update})


def client(mailer: MemoryMailer | None = None, **update) -> TestClient:
    s = settings(**update)
    fake = RoleFake(
        ROUTE_ANSWER,
        CANCELED_SQL,
        {"headline": "Canceled orders were counted.", "notes": [], "caveats": []},
    )
    llm = LLMClient(fake_config(name="gemini"), PostgresLedger(s), None, fake, sleep=lambda x: None)
    app = create_app(
        s,
        client=llm,
        recorder=TraceRecorder(s),
        store=SessionStore(),
        trace_config=TAG,
        accounts=AccountStore(s),
        mailer=mailer or MemoryMailer(),
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def cleanup():
    yield
    with connect_owner() as conn:
        conn.execute(
            "DELETE FROM trace.requests WHERE config_name LIKE %s AND kind = 'llm_call'",
            (TAG + "%",),
        )
        conn.execute("DELETE FROM trace.requests WHERE config_name LIKE %s", (TAG + "%",))
        conn.execute("DELETE FROM app.invites WHERE email LIKE '%%@accounts.test'")
        conn.execute(
            "DELETE FROM app.sessions WHERE user_id IN (SELECT id FROM app.users WHERE email LIKE '%%@accounts.test')"
        )
        conn.execute("DELETE FROM app.users WHERE email LIKE '%%@accounts.test'")


_n = [0]


def unique(prefix: str) -> str:
    _n[0] += 1
    return f"{prefix}{_n[0]}-{id(_n)}@accounts.test"


@pytest.fixture
def admin():
    email = unique("admin")
    AccountStore().create_user(email, "Admin", PW, role="admin")
    return email


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sign_in(c: TestClient, email: str, password: str = PW) -> str:
    r = c.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.json()
    return r.json()["token"]


def invite_and_join(c: TestClient, admin_token: str, name: str = "Friend") -> tuple[str, str]:
    """The whole invite flow; returns (email, the new user's token)."""
    email = unique("friend")
    r = c.post("/v1/admin/invites", json={"email": email}, headers=bearer(admin_token))
    assert r.status_code == 200
    code = r.json()["code"]
    assert c.get(f"/v1/auth/invites/{code}").json()["email"] == email
    r = c.post("/v1/auth/signup", json={"invite": code, "name": name, "password": PW})
    assert r.status_code == 200, r.json()
    return email, r.json()["token"]


# ---------- the invite flow ----------


def test_admin_invites_a_friend_who_chooses_their_own_password(admin):
    c = client()
    token = sign_in(c, admin)
    email, friend = invite_and_join(c, token)
    me = c.get("/v1/auth/me", headers=bearer(friend)).json()
    assert me["email"] == email and me["role"] == "user" and me["name"] == "Friend"
    assert sign_in(c, email)  # the password the friend chose works
    invites = c.get("/v1/admin/invites", headers=bearer(token)).json()["invites"]
    assert next(i for i in invites if i["email"] == email)["status"] == "used"


def test_an_invite_works_only_once(admin):
    c = client()
    token = sign_in(c, admin)
    code = c.post(
        "/v1/admin/invites", json={"email": unique("once")}, headers=bearer(token)
    ).json()["code"]
    assert (
        c.post("/v1/auth/signup", json={"invite": code, "name": "A", "password": PW}).status_code
        == 200
    )
    again = c.post("/v1/auth/signup", json={"invite": code, "name": "B", "password": PW})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_invite"
    assert c.get(f"/v1/auth/invites/{code}").status_code == 404


def test_revoked_and_expired_invites_are_refused(admin):
    c = client()
    token = sign_in(c, admin)
    r = c.post("/v1/admin/invites", json={"email": unique("revoked")}, headers=bearer(token)).json()
    assert c.post(
        f"/v1/admin/invites/{r['invite']['id']}/revoke", headers=bearer(token)
    ).json() == {"revoked": True}
    assert (
        c.post(
            "/v1/auth/signup", json={"invite": r["code"], "name": "X", "password": PW}
        ).status_code
        == 400
    )

    r = c.post("/v1/admin/invites", json={"email": unique("expired")}, headers=bearer(token)).json()
    with connect_owner() as conn:
        conn.execute(
            "UPDATE app.invites SET expires_at = now() - interval '1 minute' WHERE id = %s",
            (r["invite"]["id"],),
        )
    assert (
        c.post(
            "/v1/auth/signup", json={"invite": r["code"], "name": "X", "password": PW}
        ).status_code
        == 400
    )


def test_sign_up_without_an_invite_is_impossible():
    c = client()
    r = c.post("/v1/auth/signup", json={"invite": "x" * 43, "name": "Stranger", "password": PW})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_invite"
    assert (
        c.post("/v1/auth/signup", json={"invite": "short", "name": "S", "password": PW}).status_code
        == 422
    )


def test_weak_password_and_existing_email_are_refused(admin):
    c = client()
    token = sign_in(c, admin)
    code = c.post(
        "/v1/admin/invites", json={"email": unique("weak")}, headers=bearer(token)
    ).json()["code"]
    r = c.post("/v1/auth/signup", json={"invite": code, "name": "W", "password": "short"})
    assert r.json()["error"]["code"] == "weak_password"
    r = c.post("/v1/admin/invites", json={"email": admin}, headers=bearer(token))
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


# ---------- signing in ----------


def test_wrong_password_and_unknown_email_get_the_same_answer(admin):
    c = client()
    a = c.post("/v1/auth/login", json={"email": admin, "password": "wrong passphrase 9"})
    b = c.post("/v1/auth/login", json={"email": unique("nobody"), "password": PW})
    assert a.status_code == b.status_code == 401
    assert (
        a.json()
        == b.json()
        == {"error": {"code": "invalid_credentials", "message": "Email or password is wrong."}}
    )


def test_repeated_failures_lock_the_account_for_a_while(admin):
    c = client()
    for _ in range(5):
        c.post("/v1/auth/login", json={"email": admin, "password": "wrong passphrase 9"})
    r = c.post("/v1/auth/login", json={"email": admin, "password": PW})  # even the right password
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


def test_sign_out_ends_the_session(admin):
    c = client()
    token = sign_in(c, admin)
    assert c.get("/v1/auth/me", headers=bearer(token)).status_code == 200
    c.post("/v1/auth/logout", headers=bearer(token))
    assert c.get("/v1/auth/me", headers=bearer(token)).status_code == 401


def test_tokens_and_codes_are_stored_only_as_hashes(admin):
    c = client()
    token = sign_in(c, admin)
    code = c.post(
        "/v1/admin/invites", json={"email": unique("hash")}, headers=bearer(token)
    ).json()["code"]
    with connect_owner() as conn:
        dump = conn.execute(
            "SELECT string_agg(token_hash, ' ') FROM app.sessions UNION ALL "
            "SELECT string_agg(code_hash, ' ') FROM app.invites UNION ALL "
            "SELECT string_agg(password_hash, ' ') FROM app.users"
        ).fetchall()
    text = " ".join(r[0] or "" for r in dump)
    assert token not in text and code not in text and PW not in text
    assert token_hash(token) in text and token_hash(code) in text


def test_disabling_a_user_ends_their_sessions_at_once(admin):
    c = client()
    token = sign_in(c, admin)
    email, friend = invite_and_join(c, token)
    uid = c.get("/v1/auth/me", headers=bearer(friend)).json()["id"]
    assert (
        c.post(f"/v1/admin/users/{uid}/disable", headers=bearer(token)).json()["disabled"] is True
    )
    assert c.get("/v1/sessions", headers=bearer(friend)).status_code == 401
    assert c.post("/v1/auth/login", json={"email": email, "password": PW}).status_code == 401
    c.post(f"/v1/admin/users/{uid}/enable", headers=bearer(token))
    assert sign_in(c, email)


def test_an_admin_cannot_disable_themselves(admin):
    c = client()
    token = sign_in(c, admin)
    uid = c.get("/v1/auth/me", headers=bearer(token)).json()["id"]
    assert c.post(f"/v1/admin/users/{uid}/disable", headers=bearer(token)).status_code == 403


# ---------- admin only ----------


@pytest.mark.parametrize(
    "method,path",
    [("get", "/v1/admin/users"), ("get", "/v1/admin/invites"), ("post", "/v1/admin/invites")],
)
def test_admin_endpoints_refuse_users_and_the_operator_key(admin, method, path):
    c = client()
    _, friend = invite_and_join(c, sign_in(c, admin))
    kwargs = {"json": {"email": unique("x")}} if method == "post" else {}
    assert getattr(c, method)(path, headers=bearer(friend), **kwargs).status_code == 403
    assert getattr(c, method)(path, headers={"X-Access-Code": CODE}, **kwargs).status_code == 403
    assert getattr(c, method)(path, **kwargs).status_code == 401


# ---------- privacy between users ----------


def test_one_user_never_sees_another_users_conversations(admin):
    c = client()
    token = sign_in(c, admin)
    _, alice = invite_and_join(c, token, "Alice")
    _, bob = invite_and_join(c, token, "Bob")
    asked = c.post(
        "/v1/ask",
        json={"question": "How many orders were canceled?", "session_id": "acct-alice-1"},
        headers=bearer(alice),
    ).json()
    assert [
        s["session_id"] for s in c.get("/v1/sessions", headers=bearer(alice)).json()["sessions"]
    ] == ["acct-alice-1"]
    assert c.get("/v1/sessions", headers=bearer(bob)).json()["sessions"] == []
    assert c.get("/v1/sessions/acct-alice-1", headers=bearer(bob)).status_code == 404
    assert c.get(f"/v1/requests/{asked['request_id']}", headers=bearer(bob)).status_code == 404
    assert c.get(f"/v1/requests/{asked['request_id']}", headers=bearer(alice)).status_code == 200
    operator = c.get("/v1/sessions", headers={"X-Access-Code": CODE}).json()["sessions"]
    assert all(s["session_id"] != "acct-alice-1" for s in operator)


def test_admin_sees_each_users_spend_but_not_their_conversations(admin):
    c = client()
    token = sign_in(c, admin)
    email, carol = invite_and_join(c, token, "Carol")
    c.post(
        "/v1/ask",
        json={"question": "How many orders were canceled?", "session_id": "acct-carol-1"},
        headers=bearer(carol),
    )
    users = c.get("/v1/admin/users", headers=bearer(token)).json()["users"]
    row = next(u for u in users if u["email"] == email)
    assert row["questions"] == 1 and row["today_usd"] >= 0
    assert all(
        s["session_id"] != "acct-carol-1"
        for s in c.get("/v1/sessions", headers=bearer(token)).json()["sessions"]
    )


# ---------- per-user limits ----------


def test_a_user_over_their_daily_budget_is_stopped_before_any_model_call(admin):
    c = client(user_daily_cap_usd=0.0)
    token = sign_in(c, admin)
    _, dave = invite_and_join(c, token, "Dave")
    r = c.post("/v1/ask", json={"question": "How many orders were canceled?"}, headers=bearer(dave))
    assert r.status_code == 429 and r.json()["error"]["code"] == "user_budget_exhausted"
    b = c.get("/v1/budget", headers=bearer(dave)).json()
    assert b["you"] == {"today_usd": 0.0, "daily_cap_usd": 0.0}
    # admins are limited only by the overall caps
    assert (
        c.post(
            "/v1/ask", json={"question": "How many orders were canceled?"}, headers=bearer(token)
        ).status_code
        == 200
    )


def test_an_expired_or_made_up_session_is_refused():
    c = client()
    r = c.get("/v1/sessions", headers=bearer("made-up-token"))
    assert r.status_code == 401 and r.json()["error"]["message"] == "Please sign in again."


# ---------- your own account ----------


def test_change_name_freely_and_email_only_with_the_current_password(admin):
    c = client()
    token = sign_in(c, admin)
    r = c.post("/v1/account/profile", json={"name": "Sai C", "email": admin}, headers=bearer(token))
    assert r.status_code == 200 and r.json()["name"] == "Sai C"

    new = unique("renamed")
    r = c.post("/v1/account/profile", json={"name": "Sai C", "email": new}, headers=bearer(token))
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_password"
    r = c.post(
        "/v1/account/profile",
        json={"name": "Sai C", "email": new, "current_password": "not my password"},
        headers=bearer(token),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_password"

    r = c.post(
        "/v1/account/profile",
        json={"name": "Sai C", "email": new.upper(), "current_password": PW},
        headers=bearer(token),
    )
    # Not changed yet: first the code sent to the new address (test_email_codes.py).
    assert r.status_code == 200 and r.json()["pending_email"] == new  # stored in lower case
    assert c.get("/v1/auth/me", headers=bearer(token)).json()["email"] == admin


def test_an_email_that_belongs_to_someone_else_is_refused(admin):
    c = client()
    token = sign_in(c, admin)
    other, _ = invite_and_join(c, token)
    r = c.post(
        "/v1/account/profile",
        json={"name": "Admin", "email": other, "current_password": PW},
        headers=bearer(token),
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = c.post(
        "/v1/account/profile",
        json={"name": "Admin", "email": "not-an-email", "current_password": PW},
        headers=bearer(token),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_email"


def test_changing_the_password_signs_out_other_devices_but_not_this_one(admin):
    c = client()
    here, laptop = sign_in(c, admin), sign_in(c, admin)
    new_pw = "another good passphrase 2"
    r = c.post(
        "/v1/account/password",
        json={"current_password": "wrong one", "new_password": new_pw},
        headers=bearer(here),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_password"
    r = c.post(
        "/v1/account/password",
        json={"current_password": PW, "new_password": "short"},
        headers=bearer(here),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "weak_password"

    r = c.post(
        "/v1/account/password",
        json={"current_password": PW, "new_password": new_pw},
        headers=bearer(here),
    )
    assert r.status_code == 200
    assert c.get("/v1/auth/me", headers=bearer(here)).status_code == 200
    assert c.get("/v1/auth/me", headers=bearer(laptop)).status_code == 401
    assert c.post("/v1/auth/login", json={"email": admin, "password": PW}).status_code == 401
    sign_in(c, admin, new_pw)


def test_wrong_current_passwords_are_locked_out_like_sign_in(admin):
    c = client()
    token = sign_in(c, admin)
    body = {"current_password": "guess", "new_password": "another good passphrase 2"}
    codes = [
        c.post("/v1/account/password", json=body, headers=bearer(token)).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_the_operator_key_has_no_account_to_change():
    c = client()
    r = c.post(
        "/v1/account/profile",
        json={"name": "x", "email": unique("op")},
        headers={"X-Access-Code": CODE},
    )
    assert r.status_code == 403
    assert c.post("/v1/account/profile", json={"name": "x", "email": "a@b.co"}).status_code == 401


# ---------- deleting an account ----------


def test_deleting_a_user_removes_everything_but_keeps_the_spend_counted(admin):
    c = client()
    token = sign_in(c, admin)
    email, dan = invite_and_join(c, token, "Dan")
    asked = c.post(
        "/v1/ask",
        json={"question": "How many orders were canceled by Dan?", "session_id": "acct-dan-1"},
        headers=bearer(dan),
    ).json()
    rid = asked["request_id"]
    with connect_owner() as conn:  # give one model call a tiny cost, to see it survive
        conn.execute(
            "UPDATE trace.requests SET cost_usd = 0.000001 WHERE id = "
            "(SELECT id FROM trace.requests WHERE parent_id = %s LIMIT 1)",
            (rid,),
        )
        calls = conn.execute(
            "SELECT count(*), sum(cost_usd) FROM trace.requests WHERE parent_id = %s", (rid,)
        ).fetchone()
        spend_before = conn.execute("SELECT total_usd FROM trace.spend").fetchone()[0]
    assert calls[0] >= 1

    user_id = next(
        u["id"]
        for u in c.get("/v1/admin/users", headers=bearer(token)).json()["users"]
        if u["email"] == email
    )
    r = c.post(f"/v1/admin/users/{user_id}/delete", headers=bearer(token))
    assert r.status_code == 200 and r.json() == {
        "id": user_id,
        "deleted": True,
        "questions_removed": 1,
    }

    assert c.get("/v1/sessions", headers=bearer(dan)).status_code == 401  # signed out
    assert c.post("/v1/auth/login", json={"email": email, "password": PW}).status_code == 401
    emails = [u["email"] for u in c.get("/v1/admin/users", headers=bearer(token)).json()["users"]]
    invites = [
        i["email"] for i in c.get("/v1/admin/invites", headers=bearer(token)).json()["invites"]
    ]
    assert email not in emails and email not in invites
    with connect_owner() as conn:
        assert conn.execute("SELECT 1 FROM trace.requests WHERE id = %s", (rid,)).fetchone() is None
        left = conn.execute(
            "SELECT count(*), sum(cost_usd), count(question), count(response) "
            "FROM trace.requests WHERE kind = 'llm_call' AND config_name LIKE %s "
            "AND question IS NULL AND created_at >= now() - interval '10 minutes' "
            "AND cost_usd = 0.000001",
            (TAG + "%",),
        ).fetchone()
        spend_after = conn.execute("SELECT total_usd FROM trace.spend").fetchone()[0]
        text = conn.execute(
            "SELECT count(*) FROM trace.requests WHERE question LIKE '%%canceled by Dan%%'"
        ).fetchone()[0]
    assert left[0] == 1 and left[2] == 0 and left[3] == 0  # the cost row stays, without text
    assert spend_after == spend_before  # the budget still counts the money spent
    assert text == 0  # the question text is gone everywhere


def test_admins_and_yourself_cannot_be_deleted_and_users_cannot_delete(admin):
    c = client()
    token = sign_in(c, admin)
    _, friend = invite_and_join(c, token)
    users = c.get("/v1/admin/users", headers=bearer(token)).json()["users"]
    me = next(u for u in users if u["email"] == admin)
    other_admin = unique("admin2")
    AccountStore().create_user(other_admin, "Admin Two", PW, role="admin")
    users = c.get("/v1/admin/users", headers=bearer(token)).json()["users"]
    second = next(u for u in users if u["email"] == other_admin)

    assert c.post(f"/v1/admin/users/{me['id']}/delete", headers=bearer(token)).status_code == 403
    assert (
        c.post(f"/v1/admin/users/{second['id']}/delete", headers=bearer(token)).status_code == 403
    )
    assert c.post(f"/v1/admin/users/{me['id']}/delete", headers=bearer(friend)).status_code == 403
    missing = "00000000-0000-4000-8000-00000000dead"
    assert c.post(f"/v1/admin/users/{missing}/delete", headers=bearer(token)).status_code == 404


def test_the_api_role_still_cannot_delete_spend_rows_itself():
    with connect_trace() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM trace.requests WHERE false")
