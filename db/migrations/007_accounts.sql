-- 007: user accounts, sign-in sessions, and invites (invite-only sign-up).
--
-- Who can read this: only oi_trace (the API's writer for non-business data) and the owner.
-- oi_agent, which runs model-written SQL, has no access to schema app, so no question can
-- ever read accounts. Passwords are stored as scrypt hashes; session tokens and invite codes
-- are stored as SHA-256 hashes, so a copy of this table cannot be used to sign in.

CREATE SCHEMA app;

CREATE TABLE app.users (
    id            uuid PRIMARY KEY,
    email         text NOT NULL UNIQUE CHECK (email = lower(email) AND position('@' IN email) > 1),
    name          text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    password_hash text NOT NULL,
    role          text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    disabled      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

CREATE TABLE app.sessions (
    token_hash   text PRIMARY KEY,               -- sha256 of the token; the token is never stored
    user_id      uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_idx ON app.sessions (user_id);

CREATE TABLE app.invites (
    id         uuid PRIMARY KEY,
    code_hash  text NOT NULL UNIQUE,             -- sha256 of the code; the code is shown once
    email      text NOT NULL CHECK (email = lower(email)),
    created_by uuid NOT NULL REFERENCES app.users (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,
    used_by    uuid REFERENCES app.users (id),
    revoked_at timestamptz
);

GRANT USAGE ON SCHEMA app TO oi_trace;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.users, app.sessions, app.invites TO oi_trace;

-- Who asked: every request trace can carry its user, so history, traces and spend are per user.
ALTER TABLE trace.requests ADD COLUMN user_id uuid;
CREATE INDEX requests_user_idx ON trace.requests (user_id, created_at)
    WHERE kind = 'request';
