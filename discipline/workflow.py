"""
Disciplinary statement state machine.

All status changes go through `perform()`; there is no other code path that
writes `DisciplinaryStatement.status`. Each transition declares:
  * the statuses it may start from,
  * the resulting status,
  * who may perform it (checked against the *current* database row),
  * whether a reason is mandatory.

`perform()` locks the statement row (SELECT … FOR UPDATE) and compares the
optimistic `version` sent by the form, so two reviewers acting at the same
moment cannot both succeed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditEvent
from audit.services import log_event
from core.models import get_setting
from core.permissions import Perm
from core.scoping import unit_ids
from notifications.models import Notification
from notifications.services import notify

from .models import DisciplinaryStatement, WorkflowTransition

S = DisciplinaryStatement.Status


class WorkflowError(Exception):
    pass


# --------------------------------------------------------------------------- actor checks
def _is_author(user, st) -> bool:
    return st.submitted_by_id == user.pk


def _is_platoon_reviewer(user, st) -> bool:
    if not user.has_ocms_perm(Perm.STATEMENTS_REVIEW_PLATOON) or _is_author(user, st):
        return False
    companies, platoons = unit_ids(user)
    return st.platoon_id in platoons


def _is_company_reviewer(user, st) -> bool:
    if not user.has_ocms_perm(Perm.STATEMENTS_REVIEW_COMPANY) or _is_author(user, st):
        return False
    companies, _ = unit_ids(user)
    return st.company_id in companies


@dataclass(frozen=True)
class Transition:
    action: str
    label: str
    sources: frozenset
    target: str
    allowed: Callable
    reason_required: bool = False
    style: str = "primary"
    icon: str = "bi-check2"


TRANSITIONS: dict[str, Transition] = {t.action: t for t in [
    Transition("submit", "Submit for review", frozenset({S.DRAFT}), S.SUBMITTED, _is_author,
               style="primary", icon="bi-send"),
    Transition("resubmit", "Resubmit after correction", frozenset({S.RETURNED}), S.SUBMITTED, _is_author,
               style="primary", icon="bi-arrow-repeat"),
    Transition("withdraw", "Withdraw", frozenset({S.DRAFT, S.SUBMITTED, S.RETURNED}), S.WITHDRAWN, _is_author,
               reason_required=True, style="outline-secondary", icon="bi-x-circle"),
    Transition("platoon_approve", "Approve & forward", frozenset({S.SUBMITTED}), S.COMPANY_REVIEW,
               _is_platoon_reviewer, style="success", icon="bi-check2-circle"),
    Transition("platoon_return", "Return for correction", frozenset({S.SUBMITTED}), S.RETURNED,
               _is_platoon_reviewer, reason_required=True, style="warning", icon="bi-arrow-return-left"),
    Transition("platoon_reject", "Reject", frozenset({S.SUBMITTED}), S.REJECTED,
               _is_platoon_reviewer, reason_required=True, style="danger", icon="bi-x-octagon"),
    Transition("company_approve", "Final approval", frozenset({S.COMPANY_REVIEW}), S.APPROVED,
               _is_company_reviewer, style="success", icon="bi-patch-check"),
    Transition("company_return", "Return for correction", frozenset({S.COMPANY_REVIEW}), S.RETURNED,
               _is_company_reviewer, reason_required=True, style="warning", icon="bi-arrow-return-left"),
    Transition("company_reject", "Reject", frozenset({S.COMPANY_REVIEW}), S.REJECTED,
               _is_company_reviewer, reason_required=True, style="danger", icon="bi-x-octagon"),
]}


def available_actions(user, statement) -> list[Transition]:
    if not user.is_authenticated or not user.can_sign_in:
        return []
    return [t for t in TRANSITIONS.values() if statement.status in t.sources and t.allowed(user, statement)]


def _target_for(t: Transition) -> str:
    # Configurable policy: when company review is not required, platoon approval is final.
    if t.action == "platoon_approve" and not get_setting("require_company_review"):
        return S.APPROVED
    return t.target


def perform(statement_id: int, action: str, user, *, comment: str = "", expected_version: int | None = None,
            request=None) -> DisciplinaryStatement:
    t = TRANSITIONS.get(action)
    if t is None:
        raise WorkflowError("Unknown workflow action.")
    comment = (comment or "").strip()
    try:
        return _perform(statement_id, t, action, user, comment, expected_version, request)
    except (PermissionDenied, WorkflowError) as exc:
        # Denials are audited *after* the rolled-back transaction so the record survives.
        audit = getattr(exc, "audit", None)
        if audit:
            log_event(audit[0], request=request, actor=user, object_type="DisciplinaryStatement",
                      object_id=statement_id, outcome=AuditEvent.Outcome.DENIED, metadata=audit[1])
        raise


def _perform(statement_id, t, action, user, comment, expected_version, request):
    with transaction.atomic():
        st = (DisciplinaryStatement.objects.select_for_update()
              .select_related("cadet", "submitted_by").get(pk=statement_id))
        if expected_version is not None and st.version != expected_version:
            raise WorkflowError("This statement was changed by someone else. Reload the page and try again.")
        if st.status not in t.sources:
            err = WorkflowError(f"'{t.label}' is not allowed while the statement is {st.get_status_display()}.")
            err.audit = ("statement.transition_blocked", {"action": action, "status": st.status})
            raise err
        if not t.allowed(user, st):
            err = PermissionDenied("You are not the authorised actor for this step.")
            err.audit = ("statement.transition_denied", {"action": action})
            raise err
        if t.reason_required and len(comment) < 5:
            raise ValidationError("A reason (at least 5 characters) is required for this decision.")

        if action in {"submit", "resubmit"}:
            _validate_ready_for_submission(st)
            st.company_id = st.cadet.company_id
            st.platoon_id = st.cadet.platoon_id
            st.submitted_at = timezone.now()

        previous = st.status
        st.status = _target_for(t)
        st.version += 1
        st.last_transition_at = timezone.now()
        if st.status in {S.APPROVED, S.REJECTED}:
            st.decided_at = timezone.now()
        st.save()
        WorkflowTransition.objects.create(
            statement=st, action=action, from_status=previous, to_status=st.status,
            actor=user, actor_role=user.role, comment=comment,
        )
        log_event(f"statement.{action}", request=request, actor=user, obj=st,
                  metadata={"from": previous, "to": st.status, "reference": st.reference})
        if st.status == S.APPROVED:
            from .grading import recalculate

            recalculate(st.cadet, actor=user, trigger=f"statement_approved:{st.reference}")
        _notify(st, action, user)
    return st


def _validate_ready_for_submission(st):
    errors = []
    if not st.cadet.platoon_id or not st.cadet.company_id:
        errors.append("The cadet must be assigned to a company and platoon before a statement can be routed.")
    if st.cadet.is_archived:
        errors.append("The cadet record is archived.")
    if st.incident_at and st.incident_at > timezone.now():
        errors.append("Incident date cannot be in the future.")
    if len(st.description.strip()) < 20:
        errors.append("The factual description must be at least 20 characters.")
    if errors:
        raise ValidationError(errors)


def _reviewers(st, perm, unit_field):
    from accounts.models import User

    filters = {f"unit_assignments__{unit_field}_id": getattr(st, f"{unit_field}_id"),
               "unit_assignments__is_active": True, "is_active": True}
    return [u for u in User.objects.filter(**filters).exclude(pk=st.submitted_by_id).distinct()
            if u.has_ocms_perm(perm)]


def _notify(st, action, actor):
    link = f"/statements/{st.pk}/"
    ref = st.reference
    K = Notification.Kind
    key = f"{ref}-{action}-v{st.version}"
    if action in {"submit", "resubmit"}:
        kind = K.STATEMENT_SUBMITTED if action == "submit" else K.STATEMENT_RESUBMITTED
        notify(_reviewers(st, Perm.STATEMENTS_REVIEW_PLATOON, "platoon"), kind,
               f"Statement {ref} awaits your platoon review", link=link, dedupe_key=key)
    elif action == "platoon_approve" and st.status == S.COMPANY_REVIEW:
        notify(_reviewers(st, Perm.STATEMENTS_REVIEW_COMPANY, "company"), K.STATEMENT_FORWARDED,
               f"Statement {ref} forwarded for company review", link=link, dedupe_key=key)
        notify([st.submitted_by], K.STATEMENT_FORWARDED, f"Statement {ref} was forwarded to company review",
               link=link, dedupe_key=key + "-author")
    elif st.status == S.APPROVED:
        notify([st.submitted_by], K.STATEMENT_APPROVED, f"Statement {ref} received final approval",
               link=link, dedupe_key=key)
    elif st.status == S.REJECTED:
        notify([st.submitted_by], K.STATEMENT_REJECTED, f"Statement {ref} was rejected",
               message="Open the statement to read the reviewer's reason.", link=link, dedupe_key=key)
    elif st.status == S.RETURNED:
        notify([st.submitted_by], K.STATEMENT_RETURNED, f"Statement {ref} was returned for correction",
               message="Correct the statement and resubmit it.", link=link, dedupe_key=key)
