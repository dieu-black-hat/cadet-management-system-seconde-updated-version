import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from audit.models import AuditEvent
from core.models import ApplicationSetting
from discipline import workflow
from discipline.models import DisciplinaryStatement, DisciplineAssessment, WorkflowTransition
from notifications.models import Notification

S = DisciplinaryStatement.Status


def test_full_happy_path_updates_grade_history_notifications_and_audit(org, make_statement):
    u = org["users"]
    st = make_statement(severity="MAJOR")
    workflow.perform(st.pk, "submit", u["instructor"])
    st.refresh_from_db()
    assert st.status == S.SUBMITTED and st.platoon == org["platoons"]["a1"] and st.company == org["companies"]["a"]
    assert Notification.objects.filter(recipient=u["pc_a1"], kind=Notification.Kind.STATEMENT_SUBMITTED).exists()
    assert not Notification.objects.filter(recipient=u["pc_a2"]).exists()  # other platoon not notified

    workflow.perform(st.pk, "platoon_approve", u["pc_a1"])
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.COMPANY_REVIEW
    assert not DisciplineAssessment.objects.filter(cadet=st.cadet).exists()  # not counted until final approval

    workflow.perform(st.pk, "company_approve", u["cc_a"])
    st.refresh_from_db()
    assert st.status == S.APPROVED and st.decided_at
    a = DisciplineAssessment.objects.get(cadet=st.cadet, is_current=True)
    assert a.score == 80 and a.band_label == "Good" and a.policy == org["policy"]
    assert a.explanation["items"][0]["reference"] == st.reference
    assert list(WorkflowTransition.objects.filter(statement=st).values_list("action", flat=True)) == [
        "submit", "platoon_approve", "company_approve"]
    assert AuditEvent.objects.filter(event_type="statement.company_approve", object_id=str(st.pk)).exists()
    assert Notification.objects.filter(recipient=u["instructor"], kind=Notification.Kind.STATEMENT_APPROVED).exists()


def test_rejection_and_return_require_reason(org, make_statement):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    with pytest.raises(ValidationError):
        workflow.perform(st.pk, "platoon_reject", u["pc_a1"], comment="")
    with pytest.raises(ValidationError):
        workflow.perform(st.pk, "platoon_return", u["pc_a1"], comment="  ")
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.SUBMITTED


def test_return_correct_and_resubmit(org, make_statement):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    workflow.perform(st.pk, "platoon_return", u["pc_a1"], comment="Add the witness name.")
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.RETURNED
    workflow.perform(st.pk, "resubmit", u["instructor"])
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.SUBMITTED


def test_rejected_statement_never_affects_grade(org, make_statement):
    u = org["users"]
    st = make_statement(severity="SEVERE")
    workflow.perform(st.pk, "submit", u["instructor"])
    workflow.perform(st.pk, "platoon_reject", u["pc_a1"], comment="Not supported by evidence.")
    from discipline.grading import recalculate

    assert recalculate(st.cadet).score == 100


def test_wrong_platoon_and_wrong_company_cannot_decide(org, make_statement):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    with pytest.raises(PermissionDenied):
        workflow.perform(st.pk, "platoon_approve", u["pc_a2"])
    with pytest.raises(PermissionDenied):
        workflow.perform(st.pk, "platoon_approve", u["pc_b1"])
    workflow.perform(st.pk, "platoon_approve", u["pc_a1"])
    with pytest.raises(PermissionDenied):
        workflow.perform(st.pk, "company_approve", u["cc_b"])
    assert AuditEvent.objects.filter(event_type="statement.transition_denied").count() == 3


def test_cannot_skip_stages_or_repeat_decisions(org, make_statement):
    u = org["users"]
    st = make_statement()
    with pytest.raises(workflow.WorkflowError):  # company approval of a draft
        workflow.perform(st.pk, "company_approve", u["cc_a"])
    workflow.perform(st.pk, "submit", u["instructor"])
    with pytest.raises(workflow.WorkflowError):  # skip platoon stage
        workflow.perform(st.pk, "company_approve", u["cc_a"])
    workflow.perform(st.pk, "platoon_approve", u["pc_a1"])
    with pytest.raises(workflow.WorkflowError):  # duplicate decision
        workflow.perform(st.pk, "platoon_approve", u["pc_a1"])
    with pytest.raises(workflow.WorkflowError):
        workflow.perform(st.pk, "nonexistent", u["pc_a1"])


def test_author_cannot_approve_own_statement_even_with_review_permission(org, make_statement):
    from accounts.models import PermissionGrant

    u = org["users"]
    pc = u["pc_a1"]
    PermissionGrant.objects.create(user=pc, permission="statements.create", reason="dual role test",
                                   granted_by=u["admin"])
    st = make_statement(author="pc_a1")
    workflow.perform(st.pk, "submit", pc)
    actions = {t.action for t in workflow.available_actions(pc, DisciplinaryStatement.objects.get(pk=st.pk))}
    assert actions == {"withdraw"}  # may withdraw own report, never review it
    with pytest.raises(PermissionDenied):
        workflow.perform(st.pk, "platoon_approve", pc)


def test_stale_version_is_rejected(org, make_statement):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"], expected_version=1)
    with pytest.raises(workflow.WorkflowError):
        workflow.perform(st.pk, "platoon_approve", u["pc_a1"], expected_version=1)


def test_transaction_rolls_back_when_grade_calculation_fails(org, make_statement, monkeypatch):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    workflow.perform(st.pk, "platoon_approve", u["pc_a1"])

    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("discipline.grading.recalculate", boom)
    with pytest.raises(RuntimeError):
        workflow.perform(st.pk, "company_approve", u["cc_a"])
    st.refresh_from_db()
    assert st.status == S.COMPANY_REVIEW
    assert not WorkflowTransition.objects.filter(statement=st, action="company_approve").exists()


def test_platoon_approval_final_when_company_review_disabled(org, make_statement):
    ApplicationSetting.objects.update_or_create(key="require_company_review",
                                                defaults={"label": "x", "value": "false", "value_type": "bool"})
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    workflow.perform(st.pk, "platoon_approve", u["pc_a1"])
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.APPROVED


def test_submission_requires_cadet_platoon(org, make_statement):
    st = make_statement()
    cadet = st.cadet
    cadet.platoon = None
    cadet.save()
    with pytest.raises(ValidationError):
        workflow.perform(st.pk, "submit", org["users"]["instructor"])


def test_http_decision_endpoint_enforces_rules(org, make_statement, login):
    u = org["users"]
    st = make_statement()
    workflow.perform(st.pk, "submit", u["instructor"])
    # another platoon's commander cannot even see it
    r = login(u["pc_a2"]).post(f"/statements/{st.pk}/decide/", {"action": "platoon_approve", "version": 2})
    assert r.status_code == 403
    # the author cannot approve by forging the action
    r = login(u["instructor"]).post(f"/statements/{st.pk}/decide/", {"action": "platoon_approve", "version": 2})
    assert r.status_code == 403
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.SUBMITTED
    r = login(u["pc_a1"]).post(f"/statements/{st.pk}/decide/", {"action": "platoon_approve", "version": 2})
    assert r.status_code == 302
    assert DisciplinaryStatement.objects.get(pk=st.pk).status == S.COMPANY_REVIEW


def test_status_cannot_be_set_via_edit_form(org, make_statement, login):
    st = make_statement()
    c = login(org["users"]["instructor"])
    r = c.post(f"/statements/{st.pk}/edit/", {
        "cadet": st.cadet_id, "title": "Edited title", "category": org["category"].pk, "severity": "MINOR",
        "incident_at": st.incident_at.strftime("%Y-%m-%dT%H:%M"), "description": st.description,
        "status": "APPROVED", "version": st.version})
    assert r.status_code == 302
    st.refresh_from_db()
    assert st.title == "Edited title" and st.status == S.DRAFT
