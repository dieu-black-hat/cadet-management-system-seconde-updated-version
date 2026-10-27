import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction

from audit.models import AuditEvent
from cadets.models import Cadet, CadetAssignmentHistory
from discipline import grading, workflow
from discipline.models import DisciplineAssessment, DisciplinePolicy, GradeBand

CADET_POST = {"cadet_number": "OC-NEW-001", "first_name": "Aline", "last_name": "Uwase", "gender": "F",
              "admission_date": "2026-01-10", "status": "ACTIVE", "notes": ""}


def test_register_cadet_and_reject_duplicate(org, login):
    c = login(org["users"]["admin"])
    data = {**CADET_POST, "intake": org["intake"].pk, "company": org["companies"]["a"].pk,
            "platoon": org["platoons"]["a1"].pk}
    assert c.post("/cadets/new/", data).status_code == 302
    cadet = Cadet.objects.get(cadet_number="OC-NEW-001")
    assert CadetAssignmentHistory.objects.filter(cadet=cadet).count() == 1
    assert DisciplineAssessment.objects.get(cadet=cadet, is_current=True).score == 100
    r = c.post("/cadets/new/", {**data, "cadet_number": "oc-new-001"})
    assert r.status_code == 200 and "already registered" in r.content.decode()


def test_platoon_must_belong_to_company(org, login):
    c = login(org["users"]["admin"])
    r = c.post("/cadets/new/", {**CADET_POST, "intake": org["intake"].pk, "company": org["companies"]["b"].pk,
                                "platoon": org["platoons"]["a1"].pk})
    assert r.status_code == 200 and not Cadet.objects.filter(cadet_number="OC-NEW-001").exists()


def test_missing_fields_and_future_admission(org, login):
    c = login(org["users"]["admin"])
    r = c.post("/cadets/new/", {**CADET_POST, "first_name": "", "intake": org["intake"].pk,
                                "admission_date": "2099-01-01"})
    body = r.content.decode()
    assert r.status_code == 200 and "This field is required" in body and "future" in body


def test_db_constraint_unique_cadet_number(org):
    with pytest.raises(IntegrityError), transaction.atomic():
        Cadet.objects.create(cadet_number="OC-A1-001", first_name="x", last_name="y", gender="M",
                             intake=org["intake"], admission_date="2026-01-01", created_by=org["users"]["admin"])


def test_db_constraint_platoon_requires_company(org):
    with pytest.raises(IntegrityError), transaction.atomic():
        Cadet.objects.create(cadet_number="OC-X-9", first_name="x", last_name="y", gender="M", intake=org["intake"],
                             platoon=org["platoons"]["a1"], admission_date="2026-01-01",
                             created_by=org["users"]["admin"])


def test_reassignment_records_history(org, login):
    cadet = org["cadets"]["a1"]
    login(org["users"]["admin"]).post(f"/cadets/{cadet.pk}/reassign/", {
        "intake": org["intake"].pk, "company": org["companies"]["a"].pk, "platoon": org["platoons"]["a2"].pk,
        "reason": "Balancing platoon strength"})
    cadet.refresh_from_db()
    assert cadet.platoon == org["platoons"]["a2"]
    h = CadetAssignmentHistory.objects.get(cadet=cadet)
    assert h.from_platoon == org["platoons"]["a1"] and h.to_platoon == org["platoons"]["a2"]
    assert AuditEvent.objects.filter(event_type="cadet.reassigned").exists()


def test_archive_instead_of_delete(org, login):
    cadet = org["cadets"]["a1"]
    login(org["users"]["admin"]).post(f"/cadets/{cadet.pk}/archive/", {"archive": "1"})
    cadet.refresh_from_db()
    assert cadet.is_archived and Cadet.objects.filter(pk=cadet.pk).exists()
    assert login(org["users"]["pc_a1"]).get(f"/cadets/{cadet.pk}/").status_code == 403


def test_filters_and_pagination(org, login):
    c = login(org["users"]["admin"])
    for i in range(30):
        Cadet.objects.create(cadet_number=f"OC-P-{i:03d}", first_name="Page", last_name=f"Test{i:02d}", gender="M",
                             intake=org["intake"], company=org["companies"]["b"], platoon=org["platoons"]["b1"],
                             admission_date="2026-01-01", created_by=org["users"]["admin"])
    r = c.get("/cadets/?q=Page")
    assert r.context["page_obj"].paginator.count == 30 and len(r.context["page_obj"].object_list) == 24
    assert len(c.get("/cadets/?q=Page&page=2").context["page_obj"].object_list) == 6
    assert c.get(f"/cadets/?platoon={org['platoons']['a1'].pk}").context["page_obj"].paginator.count == 1
    assert c.get("/cadets/?page=999").status_code == 200  # out-of-range page is handled


def test_csv_import_all_or_nothing(org, login):
    c = login(org["users"]["admin"])
    header = "cadet_number,first_name,last_name,gender,intake_code,company_code,platoon_code,admission_date,status\n"
    bad = header + "OC-IMP-1,Ok,Row,M,INT-T,ACOY,P1,2026-01-01,ACTIVE\nOC-IMP-2,Bad,Row,X,NOPE,ACOY,P9,2026-13-01,ACTIVE\n"
    r = c.post("/cadets/import/", {"file": SimpleUploadedFile("c.csv", bad.encode())})
    assert r.status_code == 200 and "Row 3" in r.content.decode()
    assert not Cadet.objects.filter(cadet_number__startswith="OC-IMP").exists()
    good = header + "OC-IMP-1,Ok,Row,M,INT-T,ACOY,P1,2026-01-01,ACTIVE\nOC-IMP-2,Two,Row,F,INT-T,BCOY,P1,2026-01-01,\n"
    r = c.post("/cadets/import/", {"file": SimpleUploadedFile("c.csv", good.encode())})
    assert r.status_code == 302 and Cadet.objects.filter(cadet_number__startswith="OC-IMP").count() == 2


# ----------------------------------------------------------------------------- grading
def test_policy_validation_detects_overlap_and_gaps(org):
    policy = org["policy"]
    grading.validate_policy(policy)
    GradeBand.objects.create(policy=policy, label="Overlap", color="#000000", min_score=40, max_score=60)
    with pytest.raises(ValidationError):
        grading.validate_policy(policy)
    GradeBand.objects.filter(label__in=["Overlap", "Moderate"]).delete()
    with pytest.raises(ValidationError) as e:
        grading.validate_policy(policy)
    assert "not covered" in str(e.value)


def test_new_policy_version_preserves_history(org, make_statement, login):
    u = org["users"]
    st = make_statement(severity="MAJOR")
    for action, actor in [("submit", "instructor"), ("platoon_approve", "pc_a1"), ("company_approve", "cc_a")]:
        workflow.perform(st.pk, action, u[actor])
    old = DisciplineAssessment.objects.get(cadet=st.cadet, is_current=True)
    assert old.score == 80
    c = login(u["admin"])
    c.post("/statements/grading/new-version/")
    v2 = DisciplinePolicy.objects.get(version=2)
    assert not v2.is_active and v2.bands.count() == 4
    v2.severity_weights.filter(severity="MAJOR").update(points=40)
    assert c.post(f"/statements/grading/{v2.pk}/activate/").status_code == 302
    new = DisciplineAssessment.objects.get(cadet=st.cadet, is_current=True)
    assert new.policy == v2 and new.score == 60
    old.refresh_from_db()
    assert not old.is_current and old.policy.version == 1 and old.score == 80  # history unchanged
    v1 = DisciplinePolicy.objects.get(version=1)
    assert c.get(f"/statements/grading/{v1.pk}/edit/").status_code == 302  # locked version cannot be edited


def test_override_requires_reason_and_is_audited(org, login):
    cadet = org["cadets"]["a1"]
    grading.recalculate(cadet)
    with pytest.raises(ValidationError):
        grading.override(cadet, actor=org["users"]["cc_a"], score=40, reason="short")
    c = login(org["users"]["cc_a"])
    c.post(f"/cadets/{cadet.pk}/override/", {"score": 70, "reason": "Exceptional leadership during exercise"})
    a = DisciplineAssessment.objects.get(cadet=cadet, is_current=True)
    assert a.is_override and a.score == 70 and a.calculated_score == 100
    assert AuditEvent.objects.filter(event_type="assessment.override").exists()
    # an instructor may not override
    assert login(org["users"]["instructor"]).post(f"/cadets/{cadet.pk}/override/",
                                                  {"score": 1, "reason": "x" * 20}).status_code == 403


def test_poor_band_flags_for_review_but_changes_nothing_else(org, make_statement):
    u = org["users"]
    for _ in range(2):
        st = make_statement(severity="SEVERE")
        for action, actor in [("submit", "instructor"), ("platoon_approve", "pc_a1"), ("company_approve", "cc_a")]:
            workflow.perform(st.pk, action, u[actor])
    cadet = org["cadets"]["a1"]
    a = DisciplineAssessment.objects.get(cadet=cadet, is_current=True)
    assert a.score == 30 and a.requires_review
    cadet.refresh_from_db()
    assert cadet.status == Cadet.Status.ACTIVE  # never automatic dismissal
    assert u["cc_a"].notifications.filter(kind="ASSESSMENT").exists()


# ----------------------------------------------------------------------------- audit & reports & migrations
def test_audit_is_append_only(org):
    e = AuditEvent.objects.create(event_type="test")
    with pytest.raises(PermissionDenied):
        e.save()
    with pytest.raises(PermissionDenied):
        e.delete()
    with pytest.raises(Exception), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM audit_auditevent")


def test_reports_are_scoped(org, login, make_statement):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    ra = login(u["cc_a"]).get("/reports/")
    rb = login(u["cc_b"]).get("/reports/")
    assert ra.context["r"]["submitted_total"] == 1 and rb.context["r"]["submitted_total"] == 0
    pdf = login(u["cc_a"]).get("/reports/summary.pdf")
    assert pdf.status_code == 200 and b"".join(pdf.streaming_content).startswith(b"%PDF")
    bad = login(u["cc_a"]).get("/reports/?date_from=2026-10-01&date_to=2026-01-01")
    assert bad.status_code == 200  # invalid range falls back with a message


def test_no_missing_migrations(db):
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
