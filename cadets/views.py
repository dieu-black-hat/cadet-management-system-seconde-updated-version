import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.services import log_event
from core.decorators import deny, require_perm
from core.permissions import Perm
from core.scoping import visible_cadets, visible_statements
from discipline.grading import active_policy
from discipline.models import DisciplineAssessment

from . import services
from .forms import (CadetFilterForm, CadetForm, CompanyForm, ImportForm, IntakeForm, PlatoonForm,
                    ReassignForm)
from .models import Cadet, Company, Intake, Platoon, StaffAssignment


def _scoped_cadet(request, pk) -> Cadet:
    """Fetch a cadet only if it is inside the requester's scope (prevents IDOR)."""
    cadet = visible_cadets(request.user).filter(pk=pk).first()
    if cadet is None:
        if Cadet.objects.filter(pk=pk).exists():
            deny(request, "cadet outside scope", cadet_id=pk)
        raise Http404("Cadet not found")
    return cadet


def _annotated(qs):
    current = DisciplineAssessment.objects.filter(cadet=OuterRef("pk"), is_current=True)
    return qs.annotate(grade_score=Subquery(current.values("score")[:1]),
                       grade_label=Subquery(current.values("band_label")[:1]),
                       grade_color=Subquery(current.values("band_color")[:1]),
                       grade_icon=Subquery(current.values("band_icon")[:1]))


@require_perm(Perm.CADETS_VIEW)
def cadet_list(request):
    f = CadetFilterForm(request.GET or None)
    qs = _annotated(visible_cadets(request.user))
    show_archived = request.GET.get("archived") == "1" and request.user.has_ocms_perm(Perm.CADETS_EDIT)
    qs = qs.filter(is_archived=show_archived)
    sort = "name"
    if f.is_valid():
        d = f.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(first_name__icontains=d["q"]) | Q(last_name__icontains=d["q"])
                           | Q(cadet_number__icontains=d["q"]))
        for key in ("intake", "company", "platoon"):
            if d[key]:
                qs = qs.filter(**{key: d[key]})
        if d["status"]:
            qs = qs.filter(status=d["status"])
        sort = d["sort"] or "name"
    order = {"name": ("last_name", "first_name"), "number": ("cadet_number",),
             "-admission": ("-admission_date",), "score": (F("grade_score").asc(nulls_last=True), "last_name")}[sort]
    qs = qs.order_by(*order)
    page = Paginator(qs, 24).get_page(request.GET.get("page"))
    view_mode = "grid" if request.GET.get("view") == "grid" else "list"
    return render(request, "cadets/list.html", {
        "page_obj": page, "filter": f, "view_mode": view_mode, "show_archived": show_archived,
        "policy": active_policy(),
    })


@require_perm(Perm.CADETS_VIEW)
def cadet_detail(request, pk):
    cadet = _scoped_cadet(request, pk)
    u = request.user
    ctx = {"cadet": cadet, "history": cadet.assignment_history.select_related(
        "from_company", "to_company", "from_platoon", "to_platoon", "from_intake", "to_intake", "changed_by")}
    if u.has_ocms_perm(Perm.GRADING_VIEW):
        ctx["assessment"] = cadet.assessments.filter(is_current=True).select_related("policy").first()
        ctx["assessment_history"] = cadet.assessments.select_related("policy", "created_by")[:12]
        ctx["policy"] = active_policy()
    if u.has_ocms_perm(Perm.STATEMENTS_VIEW):
        ctx["statements"] = visible_statements(u).filter(cadet=cadet).order_by("-incident_at")[:25]
    if u.has_ocms_perm(Perm.MEDICAL_VIEW_SUMMARY):
        from medical.models import MedicalRecord

        ctx["fitness"] = cadet.medical_records.exclude(fitness_status=MedicalRecord.Fitness.PENDING).first() \
            or cadet.medical_records.first()
    ctx["can_override"] = u.has_ocms_perm(Perm.ASSESSMENT_OVERRIDE)
    ctx["reassign_form"] = ReassignForm(initial={"intake": cadet.intake, "company": cadet.company,
                                                 "platoon": cadet.platoon})
    log_event("cadet.viewed", request=request, obj=cadet)
    return render(request, "cadets/detail.html", ctx)


@require_perm(Perm.CADETS_VIEW)
def cadet_photo(request, pk):
    cadet = _scoped_cadet(request, pk)
    if not cadet.photo:
        raise Http404
    try:
        fh = cadet.photo.open("rb")
    except FileNotFoundError:
        raise Http404
    ext = cadet.photo.name.rsplit(".", 1)[-1].lower()
    resp = FileResponse(fh, content_type="image/png" if ext == "png" else "image/jpeg")
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_perm(Perm.CADETS_CREATE)
def cadet_create(request):
    form = CadetForm(request.POST or None, request.FILES or None,
                     can_assign=request.user.has_ocms_perm(Perm.CADETS_ASSIGN))
    if request.method == "POST" and form.is_valid():
        try:
            cadet = services.create_cadet(request, form)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f"Cadet {cadet.cadet_number} registered.")
            return redirect("cadets:detail", pk=cadet.pk)
    return render(request, "cadets/form.html", {"form": form, "is_new": True})


@require_perm(Perm.CADETS_EDIT)
def cadet_edit(request, pk):
    cadet = _scoped_cadet(request, pk)
    form = CadetForm(request.POST or None, request.FILES or None, instance=cadet)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_cadet(request, form)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, "Cadet record saved.")
            return redirect("cadets:detail", pk=cadet.pk)
    return render(request, "cadets/form.html", {"form": form, "is_new": False, "cadet": cadet})


@require_POST
@require_perm(Perm.CADETS_ASSIGN)
def cadet_reassign(request, pk):
    cadet = _scoped_cadet(request, pk)
    form = ReassignForm(request.POST)
    if form.is_valid():
        try:
            services.reassign(request, cadet, form.cleaned_data["intake"], form.cleaned_data["company"],
                              form.cleaned_data["platoon"], form.cleaned_data["reason"])
            messages.success(request, "Assignment updated and recorded in the history.")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
    else:
        messages.error(request, "Reassignment not saved: " + "; ".join(
            f"{k}: {', '.join(v)}" for k, v in form.errors.items()))
    return redirect("cadets:detail", pk=pk)


@require_POST
@require_perm(Perm.CADETS_EDIT)
def cadet_archive(request, pk):
    cadet = _scoped_cadet(request, pk)
    archive = request.POST.get("archive") == "1"
    services.set_archived(request, cadet, archive)
    messages.success(request, "Cadet archived." if archive else "Cadet restored.")
    return redirect("cadets:detail", pk=pk)


@require_POST
@require_perm(Perm.ASSESSMENT_OVERRIDE)
def cadet_override(request, pk):
    from discipline import grading

    cadet = _scoped_cadet(request, pk)
    try:
        score = int(request.POST.get("score", ""))
        grading.override(cadet, actor=request.user, score=score, reason=request.POST.get("reason", ""),
                         request=request)
        messages.success(request, "Manual override recorded with your reason.")
    except (ValueError, ValidationError) as e:
        messages.error(request, " ".join(getattr(e, "messages", ["Enter a whole-number score."])))
    return redirect("cadets:detail", pk=pk)


@require_POST
@require_perm(Perm.ASSESSMENT_OVERRIDE)
def cadet_clear_override(request, pk):
    from discipline import grading

    cadet = _scoped_cadet(request, pk)
    grading.recalculate(cadet, actor=request.user, trigger="override_cleared")
    log_event("assessment.override_cleared", request=request, obj=cadet)
    messages.success(request, "Override cleared; grade recalculated from approved statements.")
    return redirect("cadets:detail", pk=pk)


@require_perm(Perm.CADETS_IMPORT)
def cadet_import(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    errors = []
    if request.method == "POST" and form.is_valid():
        created, errors = services.import_csv(request, form.cleaned_data["file"])
        if not errors:
            messages.success(request, f"{created} cadet(s) imported.")
            return redirect("cadets:list")
        messages.error(request, "Nothing was imported. Fix the rows listed below and upload again.")
    return render(request, "cadets/import.html", {"form": form, "errors": errors,
                                                  "columns": services.REQUIRED_COLUMNS})


@require_perm(Perm.CADETS_EXPORT)
def cadet_export(request):
    qs = _annotated(visible_cadets(request.user)).filter(is_archived=False).order_by("cadet_number")
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="cadets-{timezone.localdate():%Y%m%d}.csv"'
    resp["Cache-Control"] = "no-store"
    w = csv.writer(resp)
    w.writerow(["cadet_number", "first_name", "last_name", "gender", "intake_code", "company_code", "platoon_code",
                "admission_date", "status", "discipline_grade", "discipline_score"])
    n = 0
    for c in qs:
        w.writerow([services.csv_safe(v) for v in [
            c.cadet_number, c.first_name, c.last_name, c.gender, c.intake.code, c.company.code if c.company else "",
            c.platoon.code if c.platoon else "", c.admission_date, c.status, c.grade_label or "", c.grade_score]])
        n += 1
    log_event("export.cadets_csv", request=request, metadata={"rows": n})
    return resp


# --------------------------------------------------------------------------- organisation
@require_perm(Perm.ORG_MANAGE)
def org_overview(request):
    return render(request, "cadets/org.html", {
        "intakes": Intake.objects.annotate(n=Count("cadets")),
        "companies": Company.objects.annotate(n=Count("cadets", distinct=True)).prefetch_related("platoons"),
        "platoons": Platoon.objects.select_related("company").annotate(n=Count("cadets")),
        "staff": StaffAssignment.objects.filter(is_active=True).select_related("user", "company", "platoon").order_by("company__code", "platoon__code"),
    })


ORG_FORMS = {"intake": (Intake, IntakeForm), "company": (Company, CompanyForm), "platoon": (Platoon, PlatoonForm)}


@require_perm(Perm.ORG_MANAGE)
def org_edit(request, kind, pk=None):
    if kind not in ORG_FORMS:
        raise Http404
    model, form_cls = ORG_FORMS[kind]
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = form_cls(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        log_event(f"org.{kind}_{'updated' if pk else 'created'}", request=request, obj=obj,
                  metadata={"changed": form.changed_data})
        messages.success(request, f"{model._meta.verbose_name.capitalize()} saved.")
        return redirect("cadets:org")
    return render(request, "cadets/org_form.html", {"form": form, "kind": model._meta.verbose_name,
                                                    "instance": instance})
