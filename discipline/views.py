from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.services import log_event
from core.decorators import deny, require_perm
from core.files import safe_display_name
from core.models import get_setting
from core.permissions import Perm
from core.scoping import unit_ids, visible_cadets, visible_statements

from . import grading, workflow
from .forms import (AttachmentForm, BandFormSet, CommentForm, DecisionForm, PolicyForm, StatementFilterForm,
                    StatementForm, WeightFormSet)
from .models import (DisciplinaryStatement, DisciplinePolicy, GradeBand, Severity, SeverityWeight,
                     StatementAttachment, StatementReview)

S = DisciplinaryStatement.Status


def _scoped_statement(request, pk) -> DisciplinaryStatement:
    st = visible_statements(request.user).filter(pk=pk).first()
    if st is None:
        if DisciplinaryStatement.objects.filter(pk=pk).exists():
            deny(request, "statement outside scope", statement_id=pk)
        raise Http404("Statement not found")
    return st


def _apply_filters(qs, f):
    if f.is_valid():
        d = f.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(reference__icontains=d["q"]) | Q(title__icontains=d["q"])
                           | Q(cadet__cadet_number__icontains=d["q"]) | Q(cadet__last_name__icontains=d["q"]))
        if d["status"]:
            qs = qs.filter(status=d["status"])
        if d["category"]:
            qs = qs.filter(category=d["category"])
        if d["severity"]:
            qs = qs.filter(severity=d["severity"])
        if d["date_from"]:
            qs = qs.filter(incident_at__date__gte=d["date_from"])
        if d["date_to"]:
            qs = qs.filter(incident_at__date__lte=d["date_to"])
    return qs


@require_perm(Perm.STATEMENTS_VIEW)
def statement_list(request):
    f = StatementFilterForm(request.GET or None)
    qs = _apply_filters(visible_statements(request.user), f).order_by("-created_at")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "discipline/list.html", {"page_obj": page, "filter": f, "title": "All statements",
                                                    "mode": "all"})


@require_perm(Perm.STATEMENTS_CREATE)
def my_statements(request):
    f = StatementFilterForm(request.GET or None)
    qs = _apply_filters(DisciplinaryStatement.objects.filter(submitted_by=request.user)
                        .select_related("cadet", "category"), f).order_by("-updated_at")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    counts = {s: DisciplinaryStatement.objects.filter(submitted_by=request.user, status=s).count()
              for s in [S.DRAFT, S.RETURNED, S.SUBMITTED, S.COMPANY_REVIEW, S.APPROVED, S.REJECTED]}
    return render(request, "discipline/list.html", {"page_obj": page, "filter": f, "title": "My statements",
                                                    "mode": "mine", "counts": counts})


def review_queue_qs(user):
    companies, platoons = unit_ids(user)
    q = Q(pk__in=[])
    if user.has_ocms_perm(Perm.STATEMENTS_REVIEW_PLATOON) and platoons:
        q |= Q(status=S.SUBMITTED, platoon_id__in=platoons)
    if user.has_ocms_perm(Perm.STATEMENTS_REVIEW_COMPANY) and companies:
        q |= Q(status=S.COMPANY_REVIEW, company_id__in=companies)
    return (DisciplinaryStatement.objects.filter(q).exclude(submitted_by=user)
            .select_related("cadet", "category", "submitted_by", "platoon", "company"))


@require_perm(Perm.STATEMENTS_REVIEW_PLATOON, Perm.STATEMENTS_REVIEW_COMPANY, any_of=True)
def review_queue(request):
    overdue_days = get_setting("review_overdue_days")
    qs = review_queue_qs(request.user).order_by("last_transition_at")
    now = timezone.now()
    items = [{"s": s, "age": now - (s.last_transition_at or s.created_at),
              "overdue": (now - (s.last_transition_at or s.created_at)) > timedelta(days=overdue_days)} for s in qs]
    recent = (visible_statements(request.user).filter(transitions__actor=request.user)
              .annotate(last=Max("transitions__created_at")).order_by("-last")[:10])
    return render(request, "discipline/queue.html", {"items": items, "overdue_days": overdue_days, "recent": recent})


@require_perm(Perm.STATEMENTS_CREATE)
def statement_create(request):
    cadets = visible_cadets(request.user).filter(is_archived=False)
    initial = {}
    if request.GET.get("cadet"):
        c = cadets.filter(pk=request.GET.get("cadet")).first()
        if c:
            initial["cadet"] = c
    form = StatementForm(request.POST or None, cadet_queryset=cadets, initial=initial)
    att_form = AttachmentForm(request.POST or None, request.FILES or None) if request.FILES else None
    if request.method == "POST" and form.is_valid() and (att_form is None or att_form.is_valid()):
        with transaction.atomic():
            st = form.save(commit=False)
            st.submitted_by = request.user
            st.save()
            log_event("statement.created", request=request, obj=st, metadata={"reference": st.reference})
            if att_form:
                _save_attachment(request, st, att_form)
        if request.POST.get("submit_now") == "1":
            try:
                workflow.perform(st.pk, "submit", request.user, expected_version=st.version, request=request)
                messages.success(request, f"Statement {st.reference} submitted for platoon review.")
            except (ValidationError, workflow.WorkflowError) as e:
                messages.warning(request, f"Saved as draft but not submitted: {' '.join(getattr(e, 'messages', [str(e)]))}")
        else:
            messages.success(request, f"Draft {st.reference} saved. Submit it when ready.")
        return redirect("discipline:detail", pk=st.pk)
    if request.method == "POST" and att_form is not None and not att_form.is_valid():
        messages.error(request, "Attachment rejected: " + " ".join(att_form.errors.get("file", [])))
    return render(request, "discipline/form.html", {"form": form, "is_new": True, "att_form": AttachmentForm()})


@require_perm(Perm.STATEMENTS_CREATE)
def statement_edit(request, pk):
    st = _scoped_statement(request, pk)
    if st.submitted_by_id != request.user.pk:
        deny(request, "only the author can edit", statement_id=pk)
    if not st.is_editable:
        messages.error(request, "Only drafts and returned statements can be edited.")
        return redirect("discipline:detail", pk=pk)
    cadets = visible_cadets(request.user).filter(is_archived=False)
    form = StatementForm(request.POST or None, instance=st, cadet_queryset=cadets)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = DisciplinaryStatement.objects.select_for_update().get(pk=pk)
            if not locked.is_editable or str(locked.version) != request.POST.get("version"):
                messages.error(request, "The statement changed while you were editing. Reload and try again.")
                return redirect("discipline:detail", pk=pk)
            st = form.save(commit=False)
            st.version = locked.version + 1
            st.save()
            log_event("statement.edited", request=request, obj=st, metadata={"changed": form.changed_data})
        messages.success(request, "Statement updated.")
        return redirect("discipline:detail", pk=pk)
    return render(request, "discipline/form.html", {"form": form, "is_new": False, "statement": st})


@require_perm(Perm.STATEMENTS_VIEW)
def statement_detail(request, pk):
    st = _scoped_statement(request, pk)
    actions = workflow.available_actions(request.user, st)
    can_comment = bool(actions) or (st.submitted_by_id == request.user.pk) or \
        workflow._is_platoon_reviewer(request.user, st) or workflow._is_company_reviewer(request.user, st)
    pending_since = st.last_transition_at or st.created_at
    return render(request, "discipline/detail.html", {
        "s": st, "actions": actions, "transitions": st.transitions.select_related("actor"),
        "reviews": st.reviews.select_related("author"), "attachments": st.attachments.select_related("uploaded_by"),
        "comment_form": CommentForm(), "att_form": AttachmentForm(),
        "can_attach": st.is_editable and st.submitted_by_id == request.user.pk,
        "can_comment": can_comment, "pending_for": timezone.now() - pending_since,
        "assessment": st.cadet.assessments.filter(is_current=True).select_related("policy").first()
        if request.user.has_ocms_perm(Perm.GRADING_VIEW) else None,
    })


@require_POST
@require_perm(Perm.STATEMENTS_VIEW)
def statement_transition(request, pk):
    _scoped_statement(request, pk)
    form = DecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid request.")
        return redirect("discipline:detail", pk=pk)
    d = form.cleaned_data
    try:
        st = workflow.perform(pk, d["action"], request.user, comment=d["comment"], expected_version=d["version"],
                              request=request)
        messages.success(request, f"{workflow.TRANSITIONS[d['action']].label}: statement is now "
                                  f"“{st.get_status_display()}”.")
    except PermissionDenied:
        raise
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except workflow.WorkflowError as e:
        messages.error(request, str(e))
    return redirect("discipline:detail", pk=pk)


def _save_attachment(request, st, att_form):
    f = att_form.cleaned_data["file"]
    content_type, size, sha = att_form.validated
    att = StatementAttachment.objects.create(statement=st, file=f, original_name=safe_display_name(f.name),
                                             content_type=content_type, size=size, sha256=sha,
                                             uploaded_by=request.user)
    log_event("statement.attachment_uploaded", request=request, obj=st,
              metadata={"attachment_id": att.pk, "size": size, "sha256": sha})
    return att


@require_POST
@require_perm(Perm.STATEMENTS_CREATE)
def attachment_upload(request, pk):
    st = _scoped_statement(request, pk)
    if st.submitted_by_id != request.user.pk or not st.is_editable:
        deny(request, "attachment upload not allowed", statement_id=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        if st.attachments.count() >= 10:
            messages.error(request, "A statement can have at most 10 attachments.")
        else:
            _save_attachment(request, st, form)
            messages.success(request, "Attachment uploaded.")
    else:
        messages.error(request, "Attachment rejected: " + " ".join(form.errors.get("file", [])))
    return redirect("discipline:detail", pk=pk)


@require_perm(Perm.STATEMENTS_VIEW)
def attachment_download(request, pk, att_id):
    st = _scoped_statement(request, pk)
    att = get_object_or_404(StatementAttachment, pk=att_id, statement=st)
    log_event("statement.attachment_downloaded", request=request, obj=st, metadata={"attachment_id": att.pk})
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404
    resp = FileResponse(fh, as_attachment=True, filename=att.original_name, content_type=att.content_type)
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_POST
@require_perm(Perm.STATEMENTS_VIEW)
def comment_add(request, pk):
    st = _scoped_statement(request, pk)
    allowed = st.submitted_by_id == request.user.pk or workflow._is_platoon_reviewer(request.user, st) \
        or workflow._is_company_reviewer(request.user, st)
    if not allowed:
        deny(request, "comment not allowed", statement_id=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        StatementReview.objects.create(statement=st, author=request.user, comment=form.cleaned_data["comment"])
        log_event("statement.commented", request=request, obj=st)
        messages.success(request, "Comment added.")
    else:
        messages.error(request, "Write a comment of at least 3 characters.")
    return redirect("discipline:detail", pk=pk)


# --------------------------------------------------------------------------- grading policies
@require_perm(Perm.GRADING_VIEW)
def policy_list(request):
    return render(request, "discipline/policy_list.html", {
        "policies": DisciplinePolicy.objects.prefetch_related("bands").select_related("created_by"),
        "active": grading.active_policy(),
    })


@require_perm(Perm.GRADING_VIEW)
def policy_detail(request, pk):
    policy = get_object_or_404(DisciplinePolicy.objects.prefetch_related("bands", "severity_weights"), pk=pk)
    problems = []
    try:
        grading.validate_policy(policy)
    except ValidationError as e:
        problems = e.messages
    return render(request, "discipline/policy_detail.html", {"policy": policy, "problems": problems,
                                                             "assessed": policy.assessments.filter(is_current=True).count()})


@require_POST
@require_perm(Perm.GRADING_MANAGE)
def policy_new_version(request):
    """Create a new, editable draft version pre-filled from the active policy."""
    base = grading.active_policy() or DisciplinePolicy.objects.first()
    with transaction.atomic():
        next_version = (DisciplinePolicy.objects.aggregate(m=Max("version"))["m"] or 0) + 1
        new = DisciplinePolicy.objects.create(
            name=base.name if base else "Discipline policy", version=next_version,
            description=base.description if base else "", base_score=base.base_score if base else 100,
            period_days=base.period_days if base else 0, created_by=request.user)
        if base:
            for b in base.bands.all():
                GradeBand.objects.create(policy=new, label=b.label, color=b.color, icon=b.icon, min_score=b.min_score,
                                         max_score=b.max_score, description=b.description,
                                         requires_review=b.requires_review)
            for w in base.severity_weights.all():
                SeverityWeight.objects.create(policy=new, severity=w.severity, points=w.points)
        else:
            for sev, pts in zip(Severity.values, [5, 10, 20, 35]):
                SeverityWeight.objects.create(policy=new, severity=sev, points=pts)
        log_event("grading.policy_drafted", request=request, obj=new, metadata={"version": next_version})
    messages.info(request, f"Draft version {next_version} created. Adjust it, then activate.")
    return redirect("discipline:policy_edit", pk=new.pk)


@require_perm(Perm.GRADING_MANAGE)
def policy_edit(request, pk):
    policy = get_object_or_404(DisciplinePolicy, pk=pk)
    if policy.is_locked:
        messages.error(request, "This version has been used and is read-only. Create a new version instead.")
        return redirect("discipline:policy_detail", pk=pk)
    form = PolicyForm(request.POST or None, instance=policy)
    bands = BandFormSet(request.POST or None, instance=policy, prefix="bands")
    weights = WeightFormSet(request.POST or None, instance=policy, prefix="weights")
    if request.method == "POST" and form.is_valid() and bands.is_valid() and weights.is_valid():
        with transaction.atomic():
            form.save()
            bands.save()
            weights.save()
            log_event("grading.policy_edited", request=request, obj=policy)
        try:
            grading.validate_policy(policy)
            messages.success(request, "Draft saved and validated. You can activate it now.")
        except ValidationError as e:
            messages.warning(request, "Draft saved, but it cannot be activated yet: " + " ".join(e.messages))
        return redirect("discipline:policy_detail", pk=pk)
    return render(request, "discipline/policy_form.html", {"form": form, "bands": bands, "weights": weights,
                                                           "policy": policy})


@require_POST
@require_perm(Perm.GRADING_MANAGE)
def policy_activate(request, pk):
    policy = get_object_or_404(DisciplinePolicy, pk=pk)
    try:
        n = grading.activate_policy(policy, actor=request.user, request=request)
        messages.success(request, f"Policy v{policy.version} is now active. {n} cadet grade(s) recalculated; "
                                  "previous assessments are kept in each cadet's history.")
    except ValidationError as e:
        messages.error(request, "Cannot activate: " + " ".join(e.messages))
    return redirect("discipline:policy_detail", pk=pk)


@require_POST
@require_perm(Perm.GRADING_MANAGE)
def policy_recalculate(request):
    n = grading.recalculate_all(actor=request.user, request=request)
    messages.success(request, f"Recalculated {n} cadet grade(s) under the active policy.")
    return redirect("discipline:policy_list")
