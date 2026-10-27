"""
Transparent discipline assessment engine.

score = policy.base_score − Σ(points for the severity of every APPROVED statement
        whose incident falls inside the policy period), floored at 0.

The resulting score is mapped onto the policy's configured grade bands. Every
assessment stores the policy version used and an itemised explanation, so a
displayed grade can always be traced back to its inputs. Grades are
informational: they never trigger dismissal or any automatic sanction.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import log_event

from .models import DisciplinaryStatement, DisciplineAssessment, DisciplinePolicy, GradeBand, Severity


def active_policy() -> DisciplinePolicy | None:
    return DisciplinePolicy.objects.filter(is_active=True).prefetch_related("bands", "severity_weights").first()


def validate_policy(policy: DisciplinePolicy) -> None:
    """Bands must not overlap and must cover 0..base_score completely; all severities weighted."""
    bands = sorted(policy.bands.all(), key=lambda b: b.min_score)
    errors = []
    if not bands:
        errors.append("Define at least one grade band.")
    else:
        if bands[0].min_score > 0:
            errors.append(f"Scores 0–{bands[0].min_score - 1} are not covered by any band.")
        for prev, cur in zip(bands, bands[1:]):
            if cur.min_score <= prev.max_score:
                errors.append(f"Bands '{prev.label}' and '{cur.label}' overlap.")
            elif cur.min_score > prev.max_score + 1:
                errors.append(f"Scores {prev.max_score + 1}–{cur.min_score - 1} are not covered by any band.")
        if bands[-1].max_score < policy.base_score:
            errors.append(f"Scores {bands[-1].max_score + 1}–{policy.base_score} are not covered by any band.")
    weighted = set(policy.severity_weights.values_list("severity", flat=True))
    missing = [label for value, label in Severity.choices if value not in weighted]
    if missing:
        errors.append(f"Missing severity weights for: {', '.join(missing)}.")
    if errors:
        raise ValidationError(errors)


def band_for(policy: DisciplinePolicy, score: int) -> GradeBand | None:
    for band in policy.bands.all():
        if band.min_score <= score <= band.max_score:
            return band
    return None


def calculate(cadet, policy: DisciplinePolicy) -> dict:
    weights = {w.severity: w.points for w in policy.severity_weights.all()}
    qs = DisciplinaryStatement.objects.filter(
        cadet=cadet, status=DisciplinaryStatement.Status.APPROVED, is_archived=False
    ).select_related("category")
    if policy.period_days:
        qs = qs.filter(incident_at__gte=timezone.now() - timedelta(days=policy.period_days))
    items, total = [], 0
    for s in qs.order_by("incident_at"):
        pts = weights.get(s.severity, 0)
        total += pts
        items.append({
            "reference": s.reference, "statement_id": s.pk, "date": s.incident_at.date().isoformat(),
            "category": s.category.name, "severity": s.get_severity_display(), "points": pts,
        })
    score = max(0, policy.base_score - total)
    return {"score": score, "deductions": total, "items": items}


@transaction.atomic
def recalculate(cadet, *, actor=None, trigger="recalculation", policy=None) -> DisciplineAssessment | None:
    policy = policy or active_policy()
    if policy is None:
        return None
    result = calculate(cadet, policy)
    band = band_for(policy, result["score"])
    current = DisciplineAssessment.objects.select_for_update().filter(cadet=cadet, is_current=True).first()
    # A manual override stays in force under the same policy until reviewed again.
    if current and current.is_override and current.policy_id == policy.pk and trigger != "override_cleared":
        return current
    DisciplineAssessment.objects.filter(cadet=cadet, is_current=True).update(is_current=False)
    explanation = {
        "policy": f"v{policy.version} – {policy.name}",
        "formula": f"{policy.base_score} base − {result['deductions']} deductions",
        "period": f"last {policy.period_days} days" if policy.period_days else "all approved statements",
        "items": result["items"],
    }
    assessment = DisciplineAssessment.objects.create(
        cadet=cadet, policy=policy, score=result["score"], calculated_score=result["score"],
        band_label=band.label if band else "Unbanded", band_color=band.color if band else "#6c757d",
        band_icon=band.icon if band else "bi-question-circle", requires_review=bool(band and band.requires_review),
        approved_statement_count=len(result["items"]), explanation=explanation, created_by=actor, trigger=trigger,
    )
    if assessment.requires_review and (not current or not current.requires_review):
        _flag_for_review(cadet, assessment)
    return assessment


def _flag_for_review(cadet, assessment):
    from core.permissions import Role
    from accounts.models import User
    from notifications.models import Notification
    from notifications.services import notify

    commanders = User.objects.filter(
        role=Role.COMPANY_COMMANDER, is_active=True, unit_assignments__is_active=True,
        unit_assignments__company_id=cadet.company_id,
    ).distinct()
    notify(
        commanders, Notification.Kind.ASSESSMENT,
        title=f"Cadet {cadet.cadet_number} flagged for human review",
        message=f"Grade band '{assessment.band_label}'. This is a prompt for review, not a decision.",
        link=f"/cadets/{cadet.pk}/", dedupe_key=f"assessment-review-{assessment.pk}",
    )


@transaction.atomic
def override(cadet, *, actor, score: int, reason: str, request=None) -> DisciplineAssessment:
    if not reason or len(reason.strip()) < 10:
        raise ValidationError("A reason of at least 10 characters is required for a manual override.")
    policy = active_policy()
    if policy is None:
        raise ValidationError("No active grading policy.")
    if not (0 <= score <= policy.base_score):
        raise ValidationError(f"Score must be between 0 and {policy.base_score}.")
    calc = calculate(cadet, policy)
    band = band_for(policy, score)
    previous = DisciplineAssessment.objects.select_for_update().filter(cadet=cadet, is_current=True).first()
    DisciplineAssessment.objects.filter(cadet=cadet, is_current=True).update(is_current=False)
    assessment = DisciplineAssessment.objects.create(
        cadet=cadet, policy=policy, score=score, calculated_score=calc["score"],
        band_label=band.label if band else "Unbanded", band_color=band.color if band else "#6c757d",
        band_icon=band.icon if band else "bi-question-circle", requires_review=bool(band and band.requires_review),
        approved_statement_count=len(calc["items"]),
        explanation={"policy": f"v{policy.version} – {policy.name}",
                     "formula": f"Manual override (calculated score was {calc['score']})",
                     "period": "", "items": calc["items"]},
        is_override=True, override_reason=reason.strip(), created_by=actor, trigger="manual_override",
    )
    log_event("assessment.override", request=request, actor=actor, obj=cadet,
              metadata={"previous_score": previous.score if previous else None, "new_score": score,
                        "calculated_score": calc["score"], "reason": reason.strip()})
    return assessment


def recalculate_all(*, actor=None, request=None) -> int:
    from cadets.models import Cadet

    count = 0
    for cadet in Cadet.objects.filter(is_archived=False).iterator():
        recalculate(cadet, actor=actor, trigger="bulk_recalculation")
        count += 1
    log_event("assessment.recalculate_all", request=request, actor=actor, metadata={"cadets": count})
    return count


@transaction.atomic
def activate_policy(policy: DisciplinePolicy, *, actor, request=None) -> int:
    validate_policy(policy)
    DisciplinePolicy.objects.filter(is_active=True).exclude(pk=policy.pk).update(is_active=False)
    policy.is_active = True
    policy.was_activated = True
    policy.activated_at = timezone.now()
    policy.save(update_fields=["is_active", "was_activated", "activated_at"])
    log_event("grading.policy_activated", request=request, actor=actor, obj=policy,
              metadata={"version": policy.version})
    return recalculate_all(actor=actor, request=request)
