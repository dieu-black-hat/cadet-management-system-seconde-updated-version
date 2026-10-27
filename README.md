# Military Officer Cadet Management System (OCMS)

A Django + PostgreSQL web application that digitises officer-cadet administration: cadet records, a
traceable disciplinary-statement approval workflow, a configurable discipline grading policy, a
restricted medical module, role-specific dashboards, reports, notifications and an append-only audit trail.

> All bundled data is **synthetic**. Never load real cadet, staff or medical records into a demo.

## Technology

| Layer | Choice |
|---|---|
| Backend | Python 3.10–3.13, Django 5.2 LTS (Django ORM, auth, forms, messages, e-mail) |
| Database | PostgreSQL 14+ (migrations, constraints, an audit-protection trigger) |
| Frontend | Django templates, Bootstrap 5.3, Bootstrap Icons, Chart.js 4 — all served locally (strict CSP) |
| Files | Private storage outside any public URL; downloads only through permission-checked views |
| Reports | CSV (formula-injection safe) and PDF (ReportLab) |
| Tests | pytest + pytest-django (87 tests) |

## Quick start (Windows, in VS Code)

Prerequisites: **Python 3.10+** (tick “Add python.exe to PATH” when installing) and **PostgreSQL 14+**
(remember the password you give the `postgres` user). Docker Desktop can replace a local PostgreSQL.

1. Open this folder in VS Code (`File → Open Folder…`).
2. Open a terminal (`Terminal → New Terminal`) and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
   ```
   (or, with Docker Desktop instead of a local PostgreSQL: `... scripts\setup.ps1 -UseDocker`)

   The script creates `.venv`, installs packages, creates the database and the `.env` file, applies
   migrations, loads demo data and runs the tests.
3. Start the server: `.venv\Scripts\python manage.py runserver` — or press **F5** and pick “OCMS: run server”.
4. Open <http://127.0.0.1:8000>.

macOS/Linux: `bash scripts/setup.sh` (or `bash scripts/setup.sh --docker`), then `.venv/bin/python manage.py runserver`.

### Manual setup (any OS)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env  — then edit DATABASE_URL
# create the role/database in pgAdmin or psql:
#   CREATE ROLE cadet_user LOGIN PASSWORD 'your-password' CREATEDB;
#   CREATE DATABASE cadet_management OWNER cadet_user;
python manage.py migrate
python manage.py seed_demo         # synthetic data (only works with DJANGO_DEBUG=true)
python manage.py runserver
```

## Demo accounts

All demo accounts use the password **`Cadet@Demo2026!`** (development only — `seed_demo` refuses to run
when `DEBUG` is off).

| Role | E-mail | Scope |
|---|---|---|
| System administrator | `admin@ocms.local` | Whole institution (no clinical medical data) |
| Instructor | `instructor.acoy@ocms.local` (also `.bcoy`, `.ccoy`) | Own company |
| Platoon commander | `pc.acoy.p1@ocms.local` (… `pc.ccoy.p3`) | Own platoon |
| Company commander | `cc.acoy@ocms.local` (also `.bcoy`, `.ccoy`) | Own company |
| Doctor | `doctor@ocms.local` | Medical records of all three companies |
| Auditor | `auditor@ocms.local` | Read-only audit, reports |

A good walkthrough: sign in as `instructor.acoy`, write a statement and submit it → sign in as
`pc.acoy.p1` (if the cadet is in Platoon 1) and approve & forward → sign in as `cc.acoy` and give final
approval → open the cadet and see the recalculated grade with its explanation.

## Common commands

| Task | Command |
|---|---|
| Run the server | `python manage.py runserver` |
| Run the tests | `python -m pytest` |
| Reset demo data | `python manage.py seed_demo --reset` |
| Send overdue-review notifications (schedule daily) | `python manage.py notify_overdue` |
| Check for missing migrations | `python manage.py makemigrations --check --dry-run` |
| Dependency vulnerability scan | `pip-audit -r requirements.txt` |
| Production configuration check | `DJANGO_SETTINGS_MODULE=config.settings.production python manage.py check --deploy` |

## Project layout

```
config/          settings (base / development / production / test), urls, wsgi, asgi
core/            permission matrix, scoping, middleware, dashboards, public pages, settings, seed command
accounts/        custom User (e-mail login, role, suspension), permission grants, login throttling, user admin
cadets/          intakes, companies, platoons, cadets, assignment history, staff assignments, CSV import/export
discipline/      statements, state machine (workflow.py), grading engine (grading.py), policies
medical/         restricted medical records, revisions, private documents
reports/         scoped statistics, charts, CSV/PDF exports
notifications/   in-app (and optional e-mail) notifications
audit/           append-only audit events (+ PostgreSQL trigger)
templates/       base layouts, reusable components, one folder per module
static/          css/app.css, js/app.js, vendored Bootstrap / icons / Chart.js
tests/           pytest suite
docs/            architecture & ERD, permissions, security, deployment & backups, user guide
scripts/         setup.ps1, setup.sh, bootstrap_db.py
```

## Documentation

* [docs/architecture.md](docs/architecture.md) — modules, ERD, workflow and grading design
* [docs/permissions-matrix.md](docs/permissions-matrix.md) — roles, permissions, scoping rules
* [docs/security.md](docs/security.md) — controls mapped to OWASP ASVS L2, known limitations
* [docs/deployment.md](docs/deployment.md) — production deployment, backups and restore
* [docs/user-guide.md](docs/user-guide.md) — how each role uses the system

## Implemented features and remaining limitations

Implemented and covered by tests: e-mail login with throttling and lock-out; administrator-created
accounts with single-use set-password links; password reset; suspension/deactivation that ends live
sessions; role + per-user permission grants; unit-scoped access everywhere (lists, details, files,
statistics, exports, search); cadet CRUD with list/grid/detail, photos, assignment history, archive,
CSV import (all-or-nothing) and export; the full statement workflow with mandatory reasons, optimistic
locking, self-approval prevention and history; versioned grading policies with explanations and audited
overrides; restricted medical records with revisions and private documents; role dashboards; reports
with PDF/CSV exports; notifications; append-only audit trail; security headers and CSP.

Limitations to address before production use: no multi-factor authentication yet (recommended for
administrators — e.g. `django-otp`); no antivirus scanning of uploads (add ClamAV in the upload path);
local file storage only (use `django-storages` with a private S3-compatible bucket in production);
e-mail sending is synchronous; retention periods for medical and disciplinary records must be defined
by the institution.
