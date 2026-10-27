#!/usr/bin/env bash
# One-time setup for macOS / Linux:  bash scripts/setup.sh [--docker]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
$PY -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
[ -d .venv ] || $PY -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements-dev.txt -q
if [ "${1:-}" = "--docker" ]; then
  [ -f .env ] || cp .env.example .env
  sed -i.bak 's#^DATABASE_URL=.*#DATABASE_URL=postgres://cadet_user:change-me@localhost:5432/cadet_management#' .env && rm -f .env.bak
  docker compose up -d db && sleep 8
else
  read -rsp "Password of the PostgreSQL 'postgres' user: " PGPW; echo
  .venv/bin/python scripts/bootstrap_db.py --admin-password "$PGPW"
fi
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo --reset
.venv/bin/python -m pytest -q
echo "Setup complete. Run: .venv/bin/python manage.py runserver  then open http://127.0.0.1:8000"
