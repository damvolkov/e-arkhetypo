"""Mem0 REST server booted from a mounted config file: database ensured, schema migrated, served."""

import json
import os
from pathlib import Path
from typing import Any

import psycopg
import server_state
import uvicorn
from alembic import command
from alembic.config import Config
from psycopg import sql

##### BOOT #####

APP_DB: str = os.environ.get("APP_DB_NAME", "mem0")
CONFIG: dict[str, Any] = json.loads(Path(os.environ.get("MEM0_CONFIG", "/config/config.json")).read_text())

############################################################

### Upstream merges overrides onto a pgvector default; a foreign provider then inherits its keys and fails validation.
_initialize = server_state.initialize_state
server_state.initialize_state = lambda _default: _initialize(CONFIG)

with psycopg.connect(
    host=os.environ.get("POSTGRES_HOST", "postgres"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    user=os.environ.get("POSTGRES_USER", "postgres"),
    password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
    dbname=os.environ.get("POSTGRES_DB", "postgres"),
    autocommit=True,
) as conn:
    conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DB,)).fetchone() or conn.execute(
        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(APP_DB))
    )

command.upgrade(Config("alembic.ini"), "head")
uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("MEM0_PORT", "8000")), proxy_headers=True)
