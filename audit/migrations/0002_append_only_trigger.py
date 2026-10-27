"""Database-level protection: audit rows can be inserted but never updated or deleted."""
from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION audit_auditevent_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditevent is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_auditevent_no_update ON audit_auditevent;
CREATE TRIGGER audit_auditevent_no_update
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_block_change();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_auditevent_no_update ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_auditevent_block_change();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
