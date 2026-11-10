"""infra/auth/query: every statement `auth/postgres` runs — its two tables, and what it does with them."""

from enum import Enum

from e_infra.infra.query import Query


class AuthQuery(Query, Enum):
    """`auth/postgres`: accounts and grants, created when missing, enrolled, issued, revoked and read back."""

    LOCK = (
        "SELECT pg_advisory_xact_lock(hashtext('auth'))",
        "Serialise the creators of the tables: two concurrent ones collide on `pg_type`.",
    )
    ACCOUNT_TABLE = (
        (
            "CREATE TABLE IF NOT EXISTS auth_account ("
            "id text PRIMARY KEY, name text NOT NULL, role text NOT NULL, created timestamptz NOT NULL DEFAULT now())"
        ),
        "The accounts: keyed id, name, role, since when.",
    )
    GRANT_TABLE = (
        (
            "CREATE TABLE IF NOT EXISTS auth_grant ("
            "digest text PRIMARY KEY, owner text NOT NULL REFERENCES auth_account (id) ON DELETE CASCADE, "
            "kind text NOT NULL DEFAULT 'key', created timestamptz NOT NULL DEFAULT now(), expires timestamptz, "
            "revoked timestamptz)"
        ),
        "The grants: digest, owner account, kind, issue, expiry and revocation.",
    )
    GRANT_INDEX = (
        "CREATE INDEX IF NOT EXISTS auth_grant_owner ON auth_grant (owner) WHERE revoked IS NULL",
        "The live grants of an account.",
    )
    SEGMENTS_COLUMN = (
        "ALTER TABLE auth_account ADD COLUMN IF NOT EXISTS segments text[] NOT NULL DEFAULT '{}'",
        "The segments an account reads beyond the general: added in place to a table made before them.",
    )
    DELEGATE_COLUMN = (
        "ALTER TABLE auth_account ADD COLUMN IF NOT EXISTS delegate boolean NOT NULL DEFAULT false",
        "Whether the account acts for the people it serves, naming each call's subject: added in place.",
    )
    ENROLL = (
        (
            "INSERT INTO auth_account (id, name, role) VALUES ($1, $2, $3) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role "
            "RETURNING id, name, role, created, segments, delegate"
        ),
        "Make an account, or rename it and change its role in place; the account returned.",
    )
    ACCOUNTS = (
        "SELECT id, name, role, created, segments, delegate FROM auth_account ORDER BY created",
        "Every account, oldest first.",
    )
    SEGMENT = (
        "UPDATE auth_account SET segments = $2 WHERE id = $1 RETURNING id, name, role, created, segments, delegate",
        "Set the segments an account reads; the account returned, none when it does not exist.",
    )
    DELEGATE = (
        "UPDATE auth_account SET delegate = $2 WHERE id = $1 RETURNING id, name, role, created, segments, delegate",
        "Set whether an account acts as a delegate; the account returned, none when it does not exist.",
    )
    ISSUE = (
        "INSERT INTO auth_grant (digest, owner, kind, created, expires) VALUES ($1, $2, $3, coalesce($4, now()), $5)",
        "Record a grant: its digest, owner, kind, issue (now when none) and expiry.",
    )
    REVOKE = (
        "UPDATE auth_grant SET revoked = now() WHERE owner = $1 AND revoked IS NULL RETURNING digest",
        "Stamp every live grant of an account as revoked; the digests stamped.",
    )
    HOLDER = (
        (
            "SELECT a.id, a.name, a.role, a.created, a.segments, a.delegate, g.digest, g.kind, g.created AS issued, "
            "g.expires, g.revoked FROM auth_grant g JOIN auth_account a ON a.id = g.owner WHERE g.digest = $1"
        ),
        "The grant of a digest joined to its account.",
    )
