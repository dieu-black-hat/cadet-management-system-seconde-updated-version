from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.services import log_event
from core.decorators import deny, require_perm
from core.files import safe_display_name
from core.permissions import Perm
from core.scoping import visible_medical_cadets

from .forms import MedicalAttachmentForm, MedicalFilterForm, MedicalRecordForm
from .models import MedicalAttachment, MedicalRecord, MedicalRecordRevision

TRACKED = ["record_type", "title", "assessment_date", "fitness_status", "status", "follow_up_date",
           "clinical_notes", "command_summary"]


def _records(user):
    return MedicalRecord.objects.filter(cadet__in=visible_medical_cadets(user)).select_related("cadet", "created_by")


def _scoped_record(request, pk) -> MedicalRecord:
    rec = _records(request.user).filter(pk=pk).first()
    if rec is None:
        if MedicalRecord.objects.filter(pk=pk).exists():
            deny(request, "medical record outside scope", record_id=pk)
        raise Http404
    return rec


@require_perm(Perm.MEDICAL_VIEW_FULL)
def record_list(request):
    f = MedicalFilterForm(request.GET or None)
    qs = _records(request.user)
    if f.is_valid():
        d = f.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(cadet__cadet_number__icontains=d["q"]) | Q(cadet__last_name__icontains=d["q"])
                           | Q(reference__icontains=d["q"]) | Q(title__icontains=d["q"]))
        if d["status"]:
            qs = qs.filter(status=d["status"])
        if d["fitness"]:
            qs = qs.filter(fitness_status=d["fitness"])
        if d["record_type"]:
            qs = qs.filter(record_type=d["record_type"])
    today = timezone.localdate()
    follow_ups = _records(request.user).filter(status=MedicalRecord.Status.FOLLOW_UP).order_by("follow_up_date")[:8]
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "medical/list.html", {"page_obj": page, "filter": f, "follow_ups": follow_ups,
                                                 "today": today})


@require_perm(Perm.MEDICAL_VIEW_FULL)
def cadet_file(request, cadet_id):
    cadet = visible_medical_cadets(request.user).filter(pk=cadet_id).first()
    if cadet is None:
        deny(request, "medical file outside scope", cadet_id=cadet_id)
    log_event("medical.file_viewed", request=request, obj=cadet)
    return render(request, "medical/cadet_file.html", {"cadet": cadet,
                                                       "records": cadet.medical_records.select_related("created_by")})


@require_perm(Perm.MEDICAL_VIEW_FULL)
def record_detail(request, pk):
    rec = _scoped_record(request, pk)
    log_event("medical.record_viewed", request=request, obj=rec)
    return render(request, "medical/detail.html", {
        "r": rec, "attachments": rec.attachments.select_related("uploaded_by"),
        "revisions": rec.revisions.select_related("changed_by"), "att_form": MedicalAttachmentForm(),
    })


@require_perm(Perm.MEDICAL_EDIT, Perm.MEDICAL_VIEW_FULL)
def record_create(request):
    cadets = visible_medical_cadets(request.user)
    initial = {"assessment_date": timezone.localdate()}
    if request.GET.get("cadet"):
        c = cadets.filter(pk=request.GET["cadet"]).first()
        if c:
            initial["cadet"] = c
    form = MedicalRecordForm(request.POST or None, cadet_queryset=cadets, initial=initial)
    if request.method == "POST" and form.is_valid():
        rec = form.save(commit=False)
        rec.created_by = rec.updated_by = request.user
        rec.save()
        log_event("medical.record_created", request=request, obj=rec, metadata={"cadet_id": rec.cadet_id})
        messages.success(request, f"Medical record {rec.reference} saved.")
        return redirect("medical:detail", pk=rec.pk)
    return render(request, "medical/form.html", {"form": form, "is_new": True})


@require_perm(Perm.MEDICAL_EDIT, Perm.MEDICAL_VIEW_FULL)
def record_edit(request, pk):
    rec = _scoped_record(request, pk)
    before = {f: str(getattr(rec, f) or "") for f in TRACKED}
    form = MedicalRecordForm(request.POST or None, instance=rec, cadet_queryset=visible_medical_cadets(request.user))
    if request.method == "POST" and form.is_valid():
        changed = [f for f in form.changed_data if f in TRACKED]
        if not changed:
            messages.info(request, "No changes to save.")
            return redirect("medical:detail", pk=pk)
        with transaction.atomic():
            rec = form.save(commit=False)
            rec.updated_by = request.user
            rec.save()
            MedicalRecordRevision.objects.create(record=rec, changed_by=request.user, changed_fields=changed,
                                                 previous_values={f: before[f] for f in changed})
            # The audit trail stores field names only — never clinical content.
            log_event("medical.record_updated", request=request, obj=rec, metadata={"fields": changed})
        messages.success(request, "Medical record updated; the previous version is kept in its history.")
        return redirect("medical:detail", pk=pk)
    return render(request, "medical/form.html", {"form": form, "is_new": False, "r": rec})


@require_POST
@require_perm(Perm.MEDICAL_EDIT, Perm.MEDICAL_VIEW_FULL)
def attachment_upload(request, pk):
    rec = _scoped_record(request, pk)
    form = MedicalAttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        f = form.cleaned_data["file"]
        ctype, size, sha = form.validated
        att = MedicalAttachment.objects.create(record=rec, file=f, original_name=safe_display_name(f.name),
                                               content_type=ctype, size=size, sha256=sha, uploaded_by=request.user)
        log_event("medical.attachment_uploaded", request=request, obj=rec, metadata={"attachment_id": att.pk})
        messages.success(request, "Document uploaded to private storage.")
    else:
        messages.error(request, "Document rejected: " + " ".join(form.errors.get("file", [])))
    return redirect("medical:detail", pk=pk)


@require_perm(Perm.MEDICAL_VIEW_FULL)
def attachment_download(request, pk, att_id):
    rec = _scoped_record(request, pk)
    att = get_object_or_404(MedicalAttachment, pk=att_id, record=rec)
    log_event("medical.attachment_downloaded", request=request, obj=rec, metadata={"attachment_id": att.pk})
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404
    resp = FileResponse(fh, as_attachment=True, filename=att.original_name, content_type=att.content_type)
    resp["Cache-Control"] = "private, no-store"
    return resp
