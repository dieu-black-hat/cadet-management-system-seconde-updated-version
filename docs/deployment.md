# Production deployment, backups and recovery

## Deployment checklist

1. Linux server with Python 3.12, PostgreSQL 16, Nginx; TLS certificate (e.g. Let's Encrypt).
2. Create a dedicated OS user and a PostgreSQL role **without** superuser rights:
   `CREATE ROLE ocms_app LOGIN PASSWORD '…'; CREATE DATABASE cadet_management OWNER ocms_app;`
3. Install: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn`.
4. Environment (systemd `EnvironmentFile`, never committed):
   ```
   DJANGO_SETTINGS_MODULE=config.settings.production
   DJANGO_SECRET_KEY=<64+ random characters>
   DJANGO_ALLOWED_HOSTS=ocms.example.org
   DJANGO_CSRF_TRUSTED_ORIGINS=https://ocms.example.org
   DATABASE_URL=postgres://ocms_app:…@db-host:5432/cadet_management
   PRIVATE_MEDIA_ROOT=/srv/ocms/private_media
   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend   (+ EMAIL_HOST etc.)
   SYNTHETIC_DATA_BANNER=false
   ```
5. `manage.py migrate`, `manage.py collectstatic --noinput`, `manage.py check --deploy`.
6. Create the first administrator: `manage.py createsuperuser` (never run `seed_demo` in production — it refuses).
7. Run Gunicorn behind Nginx: `gunicorn config.wsgi -b 127.0.0.1:8001 -w 3`. Nginx serves `/static/`
   from `staticfiles/` only; **never** expose `PRIVATE_MEDIA_ROOT`.
8. Schedule `manage.py notify_overdue` daily (cron/systemd timer).
9. Restrict `PRIVATE_MEDIA_ROOT` permissions to the app user (`chmod 750`).

## Backups

* Database (daily, keep 30 days, copy off-site, encrypted):
  ```bash
  pg_dump -Fc -d "$DATABASE_URL" -f /backups/ocms-$(date +%F).dump
  gpg --encrypt -r backup@example.org /backups/ocms-$(date +%F).dump
  ```
* Private files: `rsync -a --delete /srv/ocms/private_media/ backup-host:/backups/ocms-files/` (or
  object-storage versioning).
* Back up the environment file separately in the institution's secret store.

## Restore procedure (test it at least quarterly)

```bash
createdb -O ocms_app cadet_management_restore
pg_restore -d cadet_management_restore --no-owner --role=ocms_app /backups/ocms-YYYY-MM-DD.dump
rsync -a backup-host:/backups/ocms-files/ /srv/ocms/private_media/
# point DATABASE_URL at the restored DB, then:
.venv/bin/python manage.py migrate --check && .venv/bin/python manage.py check --deploy
```
Verify: sign-in works, a cadet profile opens, a medical document downloads, the latest audit events are present.

## Upgrades

Read the Django release notes, upgrade in a staging copy, run `pytest` and `pip-audit`, back up, then
deploy and `migrate`.
