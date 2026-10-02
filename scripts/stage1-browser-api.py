"""Start a synthetic-only PostgreSQL browser fixture server on a disposable DB."""

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

if os.environ.get("E2E_DISPOSABLE_DATABASE") != "1":
    raise RuntimeError(
        "Set E2E_DISPOSABLE_DATABASE=1 to authorize synthetic browser reset"
    )
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
url = make_url(os.environ["E2E_DATABASE_URL"])
if url.host not in {"127.0.0.1", "localhost", "::1"} or not (
    url.database or ""
).endswith("_test"):
    raise RuntimeError(
        "Browser fixture requires a loopback PostgreSQL database ending _test"
    )
admin = url.set(drivername="postgresql", database="postgres").render_as_string(
    hide_password=False
)
with psycopg.connect(admin, autocommit=True) as conn:
    if not conn.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", (url.database,)
    ).fetchone():
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))
engine = create_engine(url)
with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
engine.dispose()
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["DATABASE_BACKEND"] = "postgres"
os.environ["PRIVATE_FILE_DIR"] = str(
    Path(os.environ.get("TMPDIR", "/tmp")) / "portfolio-stage1-browser-private"
)
from alembic import command
from alembic.config import Config

config = Config(str(Path(__file__).resolve().parents[1] / "services/api/alembic.ini"))
config.set_main_option(
    "script_location", str(Path(__file__).resolve().parents[1] / "services/api/alembic")
)
command.upgrade(config, "head")
import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8051)
