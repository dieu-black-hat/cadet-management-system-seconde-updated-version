import csv
import io
from datetime import date

from django import forms
from django.contrib import messages
from django.http import FileResponse, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from audit.services import log_event
from cadets.services import csv_safe
from core.decorators import require_perm
from core.permissions import Perm
from core.scoping import visible_cadets, visible_statements
from discipline.models import DisciplineAssessment

from . import services


class RangeForm(forms.Form):
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        d = super().clean()
        start, end = services.default_range()
        d["date_from"] = d.get("date_from") or start
        d["date_to"] = d.get("date_to") or end
        if d["date_from"] > d["date_to"]:
            raise forms.ValidationError("The start date must be before the end date.")
        if (d["date_to"] - d["date_from"]).days > 3 * 366:
            raise forms.ValidationError("Choose a range of three years or less.")
        return d


def _range(request):
    f = RangeForm(request.GET or None)
    if f.is_bound and f.is_valid():
        return f, f.cleaned_data["date_from"], f.cleaned_data["date_to"]
    if f.is_bound:
        messages.error(request, " ".join(f.non_field_errors()) or "Invalid dates; showing the last six months.")
    start, end = services.default_range()
    return RangeForm(initial={"date_from": start, "date_to": end}), start, end


@require_perm(Perm.REPORTS_VIEW)
def index(request):
    f, start, end = _range(request)
    r = services.build(request.user, start, end)
    return render(request, "reports/index.html", {"filter": f, "r": r, "charts": services.chart_payloads(r)})


def _filename(stem, start, end, ext):
    return f'attachment; filename="{stem}-{start:%Y%m%d}-{end:%Y%m%d}.{ext}"'


@require_perm(Perm.REPORTS_EXPORT)
def export_statements(request):
    _, start, end = _range(request)
    qs = visible_statements(request.user).filter(incident_at__date__gte=start, incident_at__date__lte=end) \
        .select_related("cadet", "category", "submitted_by", "company", "platoon").order_by("incident_at")
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = _filename("statements", start, end, "csv")
    w = csv.writer(resp)
    w.writerow(["reference", "cadet_number", "cadet_name", "company", "platoon", "incident_at", "category",
                "severity", "status", "submitted_at", "decided_at", "reported_by"])
    n = 0
    for s in qs:
        w.writerow([csv_safe(v) for v in [s.reference, s.cadet.cadet_number, s.cadet.full_name,
                                          s.company.code if s.company else "", s.platoon.name if s.platoon else "",
                                          s.incident_at.isoformat(), s.category.name, s.severity, s.status,
                                          s.submitted_at.isoformat() if s.submitted_at else "",
                                          s.decided_at.isoformat() if s.decided_at else "", s.submitted_by.email]])
        n += 1
    log_event("export.statements_csv", request=request, metadata={"rows": n, "from": str(start), "to": str(end)})
    return resp


@require_perm(Perm.REPORTS_EXPORT)
def export_assessments(request):
    cadets = visible_cadets(request.user).filter(is_archived=False)
    qs = DisciplineAssessment.objects.filter(cadet__in=cadets, is_current=True).select_related(
        "cadet", "cadet__company", "cadet__platoon", "policy").order_by("cadet__cadet_number")
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="assessments-{timezone.localdate():%Y%m%d}.csv"'
    w = csv.writer(resp)
    w.writerow(["cadet_number", "cadet_name", "company", "platoon", "score", "grade", "approved_statements",
                "policy_version", "override", "requires_review", "calculated_at"])
    n = 0
    for a in qs:
        c = a.cadet
        w.writerow([csv_safe(v) for v in [c.cadet_number, c.full_name, c.company.code if c.company else "",
                                          c.platoon.name if c.platoon else "", a.score, a.band_label,
                                          a.approved_statement_count, a.policy.version, a.is_override,
                                          a.requires_review, a.created_at.isoformat()]])
        n += 1
    log_event("export.assessments_csv", request=request, metadata={"rows": n})
    return resp


@require_perm(Perm.REPORTS_EXPORT)
def export_pdf(request):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _, start, end = _range(request)
    r = services.build(request.user, start, end)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title="OCMS discipline summary")
    st = getSampleStyleSheet()
    navy = colors.HexColor("#13294b")
    st["Title"].textColor = navy
    st["Heading2"].textColor = navy
    story = [Paragraph("Officer Cadet Management System — Discipline summary", st["Title"]),
             Paragraph(f"Period {start:%d %b %Y} to {end:%d %b %Y}. Generated {timezone.localtime():%d %b %Y %H:%M} "
                       f"for {request.user.display_name} ({request.user.get_role_display()}). Figures cover only the "
                       "units this user is authorised to see. Contains no medical information. "
                       "Demonstration data is synthetic.", st["Normal"]), Spacer(1, 8)]

    def table(rows, widths=None):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde2ea")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
                               ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        return t

    story += [Paragraph("Key figures", st["Heading2"]), table([
        ["Measure", "Value"], ["Cadets in scope", r["cadet_total"]], ["Statements submitted", r["submitted_total"]],
        ["Pending review", r["pending"]], ["Returned for correction", r["returned"]],
        ["Approval rate (decided)", f"{r['approval_rate']}%" if r["approval_rate"] is not None else "—"],
        ["Average days to decision", r["turnaround_days"] if r["turnaround_days"] is not None else "—"],
    ], [90 * mm, 40 * mm])]
    if r["by_category"]:
        story += [Paragraph("Statements by category", st["Heading2"]),
                  table([["Category", "Statements"]] + [[c["category__name"], c["n"]] for c in r["by_category"]],
                        [90 * mm, 40 * mm])]
    if r["grades"]:
        story += [Paragraph(f"Current grade distribution (policy v{r['policy'].version})", st["Heading2"]),
                  table([["Grade", "Cadets"]] + [[g["label"], g["n"]] for g in r["grades"]], [90 * mm, 40 * mm])]
    if r["by_company"]:
        story += [Paragraph("Cadets by company", st["Heading2"]),
                  table([["Company", "Cadets"]] + [[c["company__name"] or "Unassigned", c["n"]] for c in r["by_company"]],
                        [90 * mm, 40 * mm])]
    story += [Spacer(1, 10), Paragraph("Grades support human review only and never constitute a dismissal decision.",
                                       st["Italic"])]
    doc.build(story)
    buf.seek(0)
    log_event("export.summary_pdf", request=request, metadata={"from": str(start), "to": str(end)})
    resp = FileResponse(buf, as_attachment=True, filename=f"discipline-summary-{start:%Y%m%d}-{end:%Y%m%d}.pdf",
                        content_type="application/pdf")
    resp["Cache-Control"] = "no-store"
    return resp
