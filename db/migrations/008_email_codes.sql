-- 008: emailed 6-digit codes (sign-in, password reset, email change) and trusted devices.
--
-- A code is never stored, only sha256(secret || ':' || code), where the secret is a random
-- token the browser holds (in an httpOnly cookie) or the user's session token, and is itself
-- stored only as a sha256 hash. So a copy of this table cannot be used to try the million
-- possible codes offline. Codes expire after 10 minutes, work once, and die after 5 wrong
-- tries. Readable only by oi_trace and the owner, like the rest of schema app.

CREATE TABLE app.email_codes (
    id           uuid PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    purpose      text NOT NULL CHECK (purpose IN ('login', 'reset', 'email_change')),
    secret_hash  text NOT NULL,                   -- sha256 of the challenge or session token
    code_hash    text NOT NULL,
    new_email    text CHECK (new_email = lower(new_email)),  -- email_change only
    attempts     integer NOT NULL DEFAULT 0,
    sends        integer NOT NULL DEFAULT 1,
    last_sent_at timestamptz NOT NULL DEFAULT now(),
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    used_at      timestamptz
);
CREATE INDEX email_codes_user_idx ON app.email_codes (user_id, purpose, created_at);
CREATE INDEX email_codes_secret_idx ON app.email_codes (secret_hash);

-- "Trust this device for 30 days": a random token in an httpOnly cookie, stored hashed.
CREATE TABLE app.trusted_devices (
    token_hash text PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX trusted_devices_user_idx ON app.trusted_devices (user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON app.email_codes, app.trusted_devices TO oi_trace;
