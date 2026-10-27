"""Authorization, organisational isolation, medical privacy and file access."""
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from audit.models import AuditEvent
from discipline import workflow
from discipline.models import StatementAttachment
from medical.models import MedicalAttachment, MedicalRecord

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def medical(org):
    u = org["users"]
    return MedicalRecord.objects.create(
        cadet=org["cadets"]["a1"], record_type="INJURY", title="Ankle", assessment_date=date(2026, 9, 1),
        clinical_notes="SECRET-CLINICAL-NOTE sprain grade 2", fitness_status="LIMITED",
        command_summary="No running for 2 weeks.", created_by=u["doctor"], updated_by=u["doctor"])


@pytest.mark.parametrize("who,cadet,expected", [
    ("instructor", "a1", 200), ("instructor", "b1", 403),
    ("pc_a1", "a1", 200), ("pc_a1", "a2", 403), ("pc_a1", "b1", 403),
    ("cc_a", "a2", 200), ("cc_a", "b1", 403),
    ("admin", "b1", 200), ("auditor", "b1", 200),
])
def test_cadet_detail_isolation(org, login, who, cadet, expected):
    r = login(org["users"][who]).get(f"/cadets/{org['cadets'][cadet].pk}/")
    assert r.status_code == expected


def test_cadet_list_only_shows_scope(org, login):
    html = login(org["users"]["pc_a1"]).get("/cadets/").content.decode()
    assert "OC-A1-001" in html and "OC-A2-001" not in html and "OC-B1-001" not in html


def test_denied_access_is_audited(org, login):
    login(org["users"]["instructor"]).get(f"/cadets/{org['cadets']['b1'].pk}/")
    assert AuditEvent.objects.filter(event_type="authz.denied", outcome="DENIED",
                                     actor=org["users"]["instructor"]).exists()


@pytest.mark.parametrize("who,path,expected", [
    ("instructor", "/accounts/users/", 403), ("instructor", "/audit/", 403), ("instructor", "/reports/", 403),
    ("instructor", "/medical/", 403), ("instructor", "/cadets/new/", 403), ("instructor", "/settings/", 403),
    ("pc_a1", "/statements/new/", 403), ("pc_a1", "/reports/summary.pdf", 403),
    ("doctor", "/statements/", 403), ("doctor", "/medical/", 200),
    ("auditor", "/audit/", 200), ("auditor", "/accounts/users/new/", 403), ("auditor", "/medical/", 403),
    ("admin", "/medical/", 403), ("admin", "/cadets/export.csv", 200),
    ("cc_a", "/reports/statements.csv", 200), ("cc_a", "/cadets/export.csv", 403),
])
def test_role_endpoint_matrix(org, login, who, path, expected):
    assert login(org["users"][who]).get(path).status_code == expected


def test_anonymous_is_redirected_to_login(client, org):
    for path in ["/dashboard/", "/cadets/", "/medical/", "/audit/", "/reports/statements.csv"]:
        r = client.get(path)
        assert r.status_code == 302 and "/accounts/login/" in r["Location"]


def test_medical_record_only_for_medical_staff(org, login, medical):
    u = org["users"]
    assert login(u["doctor"]).get(f"/medical/{medical.pk}/").status_code == 200
    for who in ["admin", "cc_a", "pc_a1", "instructor", "auditor"]:
        assert login(u[who]).get(f"/medical/{medical.pk}/").status_code == 403, who
    assert AuditEvent.objects.filter(event_type="medical.record_viewed", actor=u["doctor"]).exists()


def test_commander_sees_only_fitness_summary(org, login, medical):
    html = login(org["users"]["cc_a"]).get(f"/cadets/{medical.cadet_id}/").content.decode()
    assert "No running for 2 weeks." in html
    assert "SECRET-CLINICAL-NOTE" not in html
    assert "SECRET-CLINICAL-NOTE" not in login(org["users"]["admin"]).get("/cadets/export.csv").content.decode()


def test_medical_not_in_search(org, login, medical):
    html = login(org["users"]["doctor"]).get("/search/?q=Ankle").content.decode()
    assert "SECRET-CLINICAL-NOTE" not in html and medical.reference not in html


def test_doctor_outside_scope_cannot_open_file(org, login):
    rec = MedicalRecord.objects.create(
        cadet=org["cadets"]["b1"], record_type="ROUTINE", title="Check", assessment_date=date(2026, 9, 1),
        clinical_notes="x", created_by=org["users"]["doctor"], updated_by=org["users"]["doctor"])
    assert login(org["users"]["doctor"]).get(f"/medical/{rec.pk}/").status_code == 403


def test_medical_document_upload_and_private_download(org, login, medical):
    u = org["users"]
    doc = login(u["doctor"])
    r = doc.post(f"/medical/{medical.pk}/documents/", {"file": SimpleUploadedFile("scan.pdf", PDF)})
    assert r.status_code == 302
    att = MedicalAttachment.objects.get(record=medical)
    assert "scan" not in att.file.name and att.file.name.startswith("medical/")  # safe generated storage name
    url = f"/medical/{medical.pk}/documents/{att.pk}/"
    resp = doc.get(url)
    assert resp.status_code == 200 and "no-store" in resp["Cache-Control"]
    assert b"".join(resp.streaming_content).startswith(b"%PDF")
    for who in ["cc_a", "admin", "instructor"]:
        assert login(u[who]).get(url).status_code == 403
    assert AuditEvent.objects.filter(event_type="medical.attachment_downloaded").count() == 1


def test_medical_update_keeps_revision_without_logging_content(org, login, medical):
    c = login(org["users"]["doctor"])
    r = c.post(f"/medical/{medical.pk}/edit/", {
        "record_type": "INJURY", "title": "Ankle", "assessment_date": "2026-09-01", "fitness_status": "FIT",
        "status": "CLOSED", "follow_up_date": "", "clinical_notes": "Recovered fully.", "command_summary": "Fit."})
    assert r.status_code == 302
    medical.refresh_from_db()
    assert medical.fitness_status == "FIT"
    rev = medical.revisions.get()
    assert "clinical_notes" in rev.changed_fields
    ev = AuditEvent.objects.get(event_type="medical.record_updated")
    assert "SECRET-CLINICAL-NOTE" not in str(ev.metadata) and "Recovered" not in str(ev.metadata)


def test_statement_attachment_rules(org, login, make_statement):
    u = org["users"]
    st = make_statement()
    ins = login(u["instructor"])
    # wrong extension
    ins.post(f"/statements/{st.pk}/attachments/", {"file": SimpleUploadedFile("x.exe", b"MZ....")})
    # extension says pdf but content is not
    ins.post(f"/statements/{st.pk}/attachments/", {"file": SimpleUploadedFile("fake.pdf", b"<script>alert(1)</script>")})
    # oversized
    ins.post(f"/statements/{st.pk}/attachments/", {"file": SimpleUploadedFile("big.pdf", PDF + b"0" * (6 * 1024 * 1024))})
    assert StatementAttachment.objects.count() == 0
    ins.post(f"/statements/{st.pk}/attachments/", {"file": SimpleUploadedFile("ok.pdf", PDF)})
    att = StatementAttachment.objects.get()
    workflow.perform(st.pk, "submit", u["instructor"])
    url = f"/statements/{st.pk}/attachments/{att.pk}/"
    assert login(u["pc_a1"]).get(url).status_code == 200
    assert login(u["pc_b1"]).get(url).status_code == 403
    assert login(u["instructor_b"]).get(url).status_code == 403
    # uploads are blocked once the statement is in review
    r = ins.post(f"/statements/{st.pk}/attachments/", {"file": SimpleUploadedFile("late.pdf", PDF)})
    assert r.status_code == 403


def test_drafts_private_to_author(org, login, make_statement):
    st = make_statement()
    assert login(org["users"]["pc_a1"]).get(f"/statements/{st.pk}/").status_code == 403
    assert login(org["users"]["admin"]).get(f"/statements/{st.pk}/").status_code == 403
    assert login(org["users"]["instructor"]).get(f"/statements/{st.pk}/").status_code == 200


def test_other_instructor_cannot_edit(org, login, make_statement):
    st = make_statement()
    assert login(org["users"]["instructor_b"]).get(f"/statements/{st.pk}/edit/").status_code == 403


def test_create_statement_rejects_cadet_outside_scope(org, login):
    c = login(org["users"]["instructor"])
    r = c.post("/statements/new/", {
        "cadet": org["cadets"]["b1"].pk, "title": "Bad", "category": org["category"].pk, "severity": "MINOR",
        "incident_at": "2026-10-01T08:00", "description": "x" * 40})
    assert r.status_code == 200 and "Select a valid choice" in r.content.decode()


def test_exports_are_scoped_and_safe(org, login):
    cadet = org["cadets"]["a1"]
    cadet.first_name = "=HYPERLINK(\"http://evil\")"
    cadet.save()
    body = login(org["users"]["admin"]).get("/cadets/export.csv").content.decode()
    assert "'=HYPERLINK" in body
    assert AuditEvent.objects.filter(event_type="export.cadets_csv").exists()
    body = login(org["users"]["cc_b"]).get("/reports/assessments.csv").content.decode()
    assert "OC-A1-001" not in body
