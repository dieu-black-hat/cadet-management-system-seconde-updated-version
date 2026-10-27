# Security

Target: OWASP ASVS 4.0 Level 2. This summarises the implemented controls and what remains to be done
before handling real data.

| Area (ASVS) | Implementation |
|---|---|
| V2 Authentication | Django PBKDF2 password hashing; minimum length 10 + common/numeric/similarity validators; no public registration; administrator-created accounts receive a single-use, expiring set-password link (no password is ever chosen or e-mailed by an admin). |
| V2 Brute force | Per-account (5 failures / 15 min) and per-IP throttling; generic error messages; all attempts audited. |
| V2 Recovery | Django token reset: single-use (token invalidated by password change), 1-hour expiry, identical response whether or not the address exists. |
| V3 Sessions | Server-side sessions, HttpOnly + SameSite=Lax cookies (Secure in production), 30-minute idle timeout, session key rotated at login, POST-only logout, suspended/deactivated users are signed out on their next request. |
| V4 Access control | Deny-by-default permission codes, organisational scoping on every queryset, object fetches through scoped querysets (IDOR), workflow actor checks on locked rows, self-approval prohibited, every denial audited. |
| V5 Validation & encoding | Django forms/ModelForms on the server, explicit field lists (no mass assignment), ORM-only queries, template auto-escaping, `json_script` for chart data, CSV formula-injection neutralisation. |
| V8 Data protection | `Cache-Control: no-store` on authenticated pages, medical data excluded from search, dashboards, exports and e-mails; commanders see only a released fitness summary. |
| V10/V12 Files | Extension allow-list, magic-byte content check, size limit, SHA-256 recorded, random storage names, storage outside web root, downloads via permission-checked views with `attachment` disposition and `nosniff`. |
| V14 Configuration | Secrets from environment, `production.py` refuses a missing/short secret key, HSTS, SSL redirect, secure cookies, CSP (`script-src 'self'`, no inline scripts, all assets local), `X-Frame-Options: DENY`, Referrer-Policy, Permissions-Policy, custom error pages without stack traces. |
| V7 Logging | Append-only `AuditEvent` (application refuses updates/deletes; PostgreSQL trigger blocks `UPDATE`/`DELETE`). Secrets and clinical notes are never written to the audit log. |

## Verified by automated tests

Cross-company and cross-platoon isolation, role/endpoint matrix, anonymous redirects, medical privacy
(records, documents, search, exports), upload validation, self-approval prevention, stage skipping,
duplicate decisions, stale versions, transaction rollback, lock-out, suspension, single-use reset
tokens, CSV injection, audit immutability.

## Required before production

1. Multi-factor authentication for administrators and commanders (e.g. `django-otp` TOTP).
2. Malware scanning of uploads (ClamAV) and private S3-compatible storage with short-lived signed URLs.
3. A dedicated database role for the app without `CREATEDB`, and a separate migration role.
4. Ship audit events to an external, write-once log store as well.
5. Defined retention and secure-deletion periods for medical and disciplinary records.
6. Run `python manage.py check --deploy` and `pip-audit` in CI; keep Django on a supported release.
7. Independent penetration test.
