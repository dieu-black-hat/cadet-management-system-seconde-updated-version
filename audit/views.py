import csv

from django import forms
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from cadets.services import csv_safe
from core.decorators import require_perm
from core.permissions import Perm

from .models import AuditEvent
from .services import log_event


class AuditFilter(forms.Form):
    actor = forms.CharField(required=False, max_length=254)
    event_type = forms.CharField(required=False, max_length=60)
    outcome = forms.ChoiceField(required=False, choices=[("", "Any outcome")] + list(AuditEvent.Outcome.choices))
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)


def _filtered(request):
    f = AuditFilter(request.GET or None)
    qs = AuditEvent.objects.all()
    if f.is_valid():
        d = f.cleaned_data
        if d["actor"]:
            qs = qs.filter(actor_email__icontains=d["actor"])
        if d["event_type"]:
            qs = qs.filter(event_type__icontains=d["event_type"])
        if d["outcome"]:
            qs = qs.filter(outcome=d["outcome"])
        if d["date_from"]:
            qs = qs.filter(created_at__date__gte=d["date_from"])
        if d["date_to"]:
            qs = qs.filter(created_at__date__lte=d["date_to"])
    return f, qs


@require_perm(Perm.AUDIT_VIEW)
def audit_list(request):
    f, qs = _filtered(request)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    types = AuditEvent.objects.values_list("event_type", flat=True).distinct().order_by("event_type")
    return render(request, "audit/list.html", {"page_obj": page, "filter": f, "types": types})


@require_perm(Perm.AUDIT_VIEW, Perm.REPORTS_EXPORT)
def audit_export(request):
    f, qs = _filtered(request)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="audit-{timezone.localdate():%Y%m%d}.csv"'
    w = csv.writer(resp)
    w.writerow(["timestamp", "actor", "role", "event", "object_type", "object_id", "outcome", "ip", "metadata"])
    rows = 0
    for e in qs[:20000]:
        w.writerow([csv_safe(v) for v in [e.created_at.isoformat(), e.actor_email, e.actor_role, e.event_type,
                                          e.object_type, e.object_id, e.outcome, e.ip_address or "", e.metadata]])
        rows += 1
    log_event("export.audit_csv", request=request, metadata={"rows": rows})
    return resp
