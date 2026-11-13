"""infra/query: `Query`, the statement the database port takes, and the banks of the statements the drivers run.

One enum per consumer module, each member its SQL and what it does. A statement is a literal in a bank, never a string
in logic: the port takes the member, and a migration file, run whole, is a `Script`. A consumer outside this package
(the auth driver) keeps its own bank in its own package, built on `Query`."""

from enum import Enum
from typing import Final, LiteralString, NamedTuple, NewType


class Query(NamedTuple):
    """One statement: its SQL — a literal, never built from text — and what it does. A consumer's bank is an enum
    whose members are `Query`: `class CacheQuery(Query, Enum)`; the port takes that member, never a string."""

    sql: LiteralString
    description: str


### a file of statements — a migration, a DDL — run whole: data versioned beside the code, never a member of a bank.
Script = NewType("Script", str)

### one row per job: the queue row while it lives, else the log's last word; picks count the attempts; a retry's
### traceback is PgQueuer's RetryRequested, whose message is the failure it carries.
READ: Final = """
SELECT j.id, j.kind, j.queue, j.args::text AS args, j.created, j.progress::text AS progress,
       q.status::text AS live, q.attempts AS retries, q.execute_after,
       l.last::text AS last, l.picks, l.errors, l.finished,
       CASE
           WHEN q.status = 'picked' THEN 'running'
           WHEN q.status = 'queued' AND q.execute_after > now() THEN
               CASE WHEN q.attempts > 0 THEN 'retryable' ELSE 'scheduled' END
           WHEN q.status = 'queued' THEN CASE WHEN q.attempts > 0 THEN 'retryable' ELSE 'available' END
           WHEN q.status = 'failed' THEN 'failed'
           WHEN l.last = 'successful' THEN 'completed'
           WHEN l.last IN ('exception', 'failed') THEN 'failed'
           WHEN l.last IN ('canceled', 'deleted') THEN 'cancelled'
           ELSE 'available'
       END AS state
FROM background.job j
LEFT JOIN pgqueuer q ON q.id = j.id
LEFT JOIN LATERAL (
    SELECT (array_agg(status ORDER BY created DESC, id DESC)
                FILTER (WHERE status NOT IN ('queued', 'picked')))[1] AS last,
           count(*) FILTER (WHERE status = 'picked') AS picks,
           coalesce(array_agg(CASE traceback->>'exception_type' WHEN 'RetryRequested' THEN traceback->>'exception_message'
                ELSE (traceback->>'exception_type') || ': ' || (traceback->>'exception_message') END
                ORDER BY created, id) FILTER (WHERE traceback IS NOT NULL), '{}') AS errors,
           max(created) FILTER (WHERE status NOT IN ('queued', 'picked')) AS finished
    FROM pgqueuer_log WHERE job_id = j.id
) l ON true
"""
### a job's filter: a kind and a state, either one NULL for any.
WHERE: Final = "($1::text IS NULL OR kind = $1) AND ($2::text IS NULL OR state = $2)"


class QueueQuery(Query, Enum):
    """`queue/pgqueuer`: the driver's `background` schema — one row per job — and how it is written and read."""

    SCHEMA = ("CREATE SCHEMA IF NOT EXISTS background", "The schema of the driver's own tables.")
    TABLE = (
        (
            "CREATE TABLE IF NOT EXISTS background.job ("
            "id bigint PRIMARY KEY, kind text NOT NULL, queue text NOT NULL, args jsonb NOT NULL, attempts int NOT NULL, "
            "created timestamptz NOT NULL DEFAULT now(), progress jsonb)"
        ),
        "The jobs: each one's kind, queue, args, attempts and latest snapshot, which PgQueuer's own tables drop.",
    )
    INDEX = (
        "CREATE INDEX IF NOT EXISTS job_kind_created ON background.job (kind, created DESC)",
        "The jobs of a kind, newest first.",
    )
    RECORD = (
        "INSERT INTO background.job (id, kind, queue, args, attempts) VALUES ($1, $2, $3, $4::jsonb, $5)",
        "Record a job just enqueued: its id, kind, queue, args and attempts.",
    )
    REPORT = ("UPDATE background.job SET progress = $2::jsonb WHERE id = $1", "Replace a job's latest snapshot.")
    ONE = (f"SELECT * FROM ({READ}) r WHERE id = $1", "One job by id, with its state.")  # noqa: S608 — constants only, values bound
    MANY = (
        f"SELECT * FROM ({READ}) r WHERE {WHERE} ORDER BY created DESC, id DESC LIMIT $3",  # noqa: S608 — constants only, values bound
        "The newest jobs of a kind and a state, up to a limit.",
    )
    CANCELLED = (
        "SELECT 1 FROM pgqueuer_log WHERE job_id = $1 AND status IN ('canceled', 'deleted') LIMIT 1",
        "A cancel already logged for the job: what a NOTIFY that came before the job's scope existed would have said.",
    )
    NOTIFY = ("SELECT pg_notify($1, $2)", "A NOTIFY on a channel with a payload.")
    HEALTH = ("SELECT 1", "One trivial statement: the database answers.")


class CacheQuery(Query, Enum):
    """`cache/postgres`: the `cache` table, created when missing, read by keys and written by rows."""

    LOCK = (
        "SELECT pg_advisory_xact_lock(hashtext('cache'))",
        "Serialise the creators of the table: two concurrent ones collide on `pg_type`.",
    )
    SCHEMA = (
        (
            "CREATE TABLE IF NOT EXISTS cache (namespace text NOT NULL, key text NOT NULL, value bytea NOT NULL, "
            "expires timestamptz, PRIMARY KEY (namespace, key))"
        ),
        "The values of every namespace, each with its expiry.",
    )
    GET = (
        "SELECT key, value FROM cache WHERE namespace = $1 AND key = ANY($2) AND (expires IS NULL OR expires > now())",
        "The live values of a namespace under a list of keys.",
    )
    PUT = (
        (
            "INSERT INTO cache (namespace, key, value, expires) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (namespace, key) DO UPDATE SET value = EXCLUDED.value, expires = EXCLUDED.expires"
        ),
        "Write one value under a namespace and key, replacing what it held.",
    )


class AwaQuery(Query, Enum):
    """`queue/awa`: the driver's own `background.progress` table, kept apart from awa's schema, and its probe."""

    SCHEMA = ("CREATE SCHEMA IF NOT EXISTS background", "The schema of the driver's own tables.")
    PROGRESS = (
        (
            "CREATE TABLE IF NOT EXISTS background.progress ("
            "job bigint PRIMARY KEY, snapshot jsonb NOT NULL, updated timestamptz NOT NULL DEFAULT now())"
        ),
        "The latest snapshot of each job: awa clears a job's progress when it completes.",
    )
    REPORT = (
        (
            "INSERT INTO background.progress (job, snapshot) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (job) DO UPDATE SET snapshot = EXCLUDED.snapshot, updated = now()"
        ),
        "Upsert a job's latest snapshot.",
    )
    SNAPSHOTS = (
        (
            "SELECT job, snapshot FROM background.progress "
            "WHERE job IN (SELECT jsonb_array_elements_text($1::jsonb)::bigint)"
        ),
        "The snapshots of the jobs in a JSON array of ids: awa binds no array parameter.",
    )
    HEALTH = ("SELECT 1", "One trivial statement: the queue's database answers.")


class SqliteQuery(Query, Enum):
    """`store/sqlite`: the one `kv` table, read, written and walked by key."""

    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)",
        "The key-value table, created when missing.",
    )
    GET = ("SELECT value FROM kv WHERE key = ?", "The value under a key.")
    SET = (
        "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
        "Write one value under a key, replacing what it held.",
    )
    DELETE = ("DELETE FROM kv WHERE key = ?", "Remove a key; absent is not an error.")
    KEYS = ("SELECT key FROM kv WHERE key LIKE ? ORDER BY key", "The keys under a LIKE pattern, in key order.")
    HEALTH = ("SELECT 1", "One trivial statement: the file answers.")


class DatabaseQuery(Query, Enum):
    """`database/psqlpy` and `database/asyncpg`: whether a database exists, and that the pool answers."""

    FOUND = ("SELECT 1 FROM pg_database WHERE datname = $1", "Whether a database of this name exists on the server.")
    HEALTH = ("SELECT 1", "One trivial statement: the pool answers.")
