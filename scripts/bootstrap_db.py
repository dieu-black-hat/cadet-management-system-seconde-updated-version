"""
Create the application database role and database on a local PostgreSQL server.

    python scripts/bootstrap_db.py --admin-user postgres --admin-password <pw> --app-password <pw>

Uses psycopg directly, so it works on Windows, macOS and Linux without psql.
Writes DATABASE_URL into .env (creating .env from .env.example if needed).
"""
import argparse
import re
import secrets
import shutil
import sys
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent


def ensure_env(database_url: str) -> None:
    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
    text = env.read_text(encoding="utf-8")
    text = re.sub(r"^DATABASE_URL=.*$", f"DATABASE_URL={database_url}", text, flags=re.M)
    if "replace-with-a-long-random-value" in text:
        text = text.replace("replace-with-a-long-random-value", secrets.token_urlsafe(64))
    env.write_text(text, encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", default="5432")
    p.add_argument("--admin-user", default="postgres")
    p.add_argument("--admin-password", required=True)
    p.add_argument("--app-user", default="cadet_user")
    p.add_argument("--app-password", default=None)
    p.add_argument("--db-name", default="cadet_management")
    a = p.parse_args()
    app_pw = a.app_password or secrets.token_urlsafe(18)
    try:
        conn = psycopg.connect(host=a.host, port=a.port, user=a.admin_user, password=a.admin_password,
                               dbname="postgres", autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        sys.exit(f"Could not connect to PostgreSQL as {a.admin_user}@{a.host}:{a.port}: {e}")
    with conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (a.app_user,)).fetchone()
        if exists:
            conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {} CREATEDB").format(
                sql.Identifier(a.app_user), sql.Literal(app_pw)))
        else:
            conn.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} CREATEDB").format(
                sql.Identifier(a.app_user), sql.Literal(app_pw)))
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (a.db_name,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(a.db_name), sql.Identifier(a.app_user)))
    url = f"postgres://{a.app_user}:{app_pw}@{a.host}:{a.port}/{a.db_name}"
    ensure_env(url)
    print(f"Database '{a.db_name}' and role '{a.app_user}' are ready; DATABASE_URL written to .env")


if __name__ == "__main__":
    main()
