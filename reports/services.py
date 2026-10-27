"""
Report calculations. Every figure is computed from querysets that have already
been restricted to the requesting user's organisational scope. Medical data is
never included in reports.
"""
from collections import OrderedDict
from datetime import date, timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.scoping import visible_cadets, visible_statements
from discipline.grading import active_policy
from discipline.models import DisciplinaryStatement, DisciplineAssessment

S = DisciplinaryStatement.Status


def default_range():
    today = timezone.localdate()
    return today - timedelta(days=180), today


def _months(start: date, end: date):
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
    return out


def build(user, start: date, end: date) -> dict:
    cadets = visible_cadets(user).filter(is_archived=False)
    stmts = visible_statements(user).filter(incident_at__date__gte=start, incident_at__date__lte=end)

    by_company = list(cadets.values("company__name").annotate(n=Count("id")).order_by("company__name"))
    by_intake = list(cadets.values("intake__code").annotate(n=Count("id")).order_by("intake__code"))
    by_status = {r["status"]: r["n"] for r in cadets.values("status").annotate(n=Count("id"))}

    status_counts = {r["status"]: r["n"] for r in stmts.values("status").annotate(n=Count("id"))}
    by_category = list(stmts.values("category__name").annotate(n=Count("id")).order_by("-n"))
    by_severity = {r["severity"]: r["n"] for r in stmts.values("severity").annotate(n=Count("id"))}

    months = _months(start, end)
    monthly = OrderedDict((m, {"submitted": 0, "approved": 0}) for m in months)
    for r in stmts.exclude(status=S.DRAFT).annotate(m=TruncMonth("incident_at")).values("m").annotate(n=Count("id")):
        key = timezone.localtime(r["m"]).date().replace(day=1) if hasattr(r["m"], "tzinfo") else r["m"]
        if key in monthly:
            monthly[key]["submitted"] = r["n"]
    for r in stmts.filter(status=S.APPROVED).annotate(m=TruncMonth("incident_at")).values("m").annotate(n=Count("id")):
        key = timezone.localtime(r["m"]).date().replace(day=1) if hasattr(r["m"], "tzinfo") else r["m"]
        if key in monthly:
            monthly[key]["approved"] = r["n"]

    decided = stmts.filter(status__in=[S.APPROVED, S.REJECTED], submitted_at__isnull=False, decided_at__isnull=False)
    turnaround = decided.annotate(d=ExpressionWrapper(F("decided_at") - F("submitted_at"),
                                                      output_field=DurationField())).aggregate(avg=Avg("d"))["avg"]
    finished = status_counts.get(S.APPROVED, 0) + status_counts.get(S.REJECTED, 0)
    submitted_total = sum(v for k, v in status_counts.items() if k not in (S.DRAFT, S.WITHDRAWN))

    platoons = list(stmts.filter(status=S.APPROVED).values("platoon__company__code", "platoon__name")
                    .annotate(n=Count("id")).order_by("platoon__company__code", "platoon__name"))

    policy = active_policy()
    grades = []
    if policy:
        current = DisciplineAssessment.objects.filter(cadet__in=cadets, is_current=True)
        counts = {r["band_label"]: r["n"] for r in current.values("band_label").annotate(n=Count("id"))}
        grades = [{"label": b.label, "color": b.color, "n": counts.get(b.label, 0)} for b in policy.bands.all()]
    review_flags = DisciplineAssessment.objects.filter(cadet__in=cadets, is_current=True, requires_review=True) \
        .select_related("cadet")[:15]

    return {
        "start": start, "end": end, "cadet_total": cadets.count(),
        "by_company": by_company, "by_intake": by_intake, "by_status": by_status,
        "status_counts": status_counts, "by_category": by_category, "by_severity": by_severity,
        "monthly": monthly, "turnaround_days": round(turnaround.total_seconds() / 86400, 1) if turnaround else None,
        "approval_rate": round(100 * status_counts.get(S.APPROVED, 0) / finished) if finished else None,
        "rejection_rate": round(100 * status_counts.get(S.REJECTED, 0) / finished) if finished else None,
        "returned": status_counts.get(S.RETURNED, 0), "pending": status_counts.get(S.SUBMITTED, 0)
        + status_counts.get(S.COMPANY_REVIEW, 0), "submitted_total": submitted_total,
        "platoons": platoons, "grades": grades, "policy": policy, "review_flags": review_flags,
    }


def chart_payloads(r: dict) -> dict:
    status_labels = dict(S.choices)
    return {
        "monthly": {"type": "line", "labels": [m.strftime("%b %Y") for m in r["monthly"]],
                    "datasets": [{"label": "Submitted", "data": [v["submitted"] for v in r["monthly"].values()]},
                                 {"label": "Approved", "data": [v["approved"] for v in r["monthly"].values()]}]},
        "status": {"type": "doughnut", "labels": [status_labels[k] for k in r["status_counts"]],
                   "datasets": [{"label": "Statements", "data": list(r["status_counts"].values())}]},
        "category": {"type": "bar", "horizontal": True, "legend": False,
                     "labels": [c["category__name"] for c in r["by_category"]],
                     "datasets": [{"label": "Statements", "data": [c["n"] for c in r["by_category"]]}]},
        "grades": {"type": "bar", "legend": False, "labels": [g["label"] for g in r["grades"]],
                   "datasets": [{"label": "Cadets", "data": [g["n"] for g in r["grades"]],
                                 "backgroundColor": [g["color"] for g in r["grades"]]}]},
        "company": {"type": "bar", "legend": False, "labels": [c["company__name"] or "Unassigned" for c in r["by_company"]],
                    "datasets": [{"label": "Cadets", "data": [c["n"] for c in r["by_company"]]}]},
        "platoons": {"type": "bar", "legend": False,
                     "labels": [f"{p['platoon__company__code']} {p['platoon__name']}" for p in r["platoons"]],
                     "datasets": [{"label": "Approved statements", "data": [p["n"] for p in r["platoons"]]}]},
    }
