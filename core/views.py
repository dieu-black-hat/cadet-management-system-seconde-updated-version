from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.forms import StyledFormMixin
from accounts.models import LoginAttempt, User
from audit.models import AuditEvent
from audit.services import client_ip, log_event
from cadets.models import Cadet, Company, Intake, Platoon
from discipline.grading import active_policy
from discipline.models import DisciplinaryStatement, DisciplineAssessment

from .decorators import require_perm
from .models import ApplicationSetting, ContactMessage, get_setting
from .permissions import Perm, Role
from .scoping import unit_ids, visible_cadets, visible_statements

S = DisciplinaryStatement.Status


# --------------------------------------------------------------------------- public pages
def home(request):
    return render(request, "public/home.html")


def about(request):
    return render(request, "public/about.html")


def services(request):
    return render(request, "public/services.html")


class ContactForm(StyledFormMixin, forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5, "col": "col-12", "maxlength": 3000}),
                   "subject": forms.TextInput(attrs={"col": "col-12"})}

    def clean_website(self):  # honeypot field
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Invalid submission.")
        return ""


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST":
        ip = client_ip(request)
        recent = ContactMessage.objects.filter(ip_address=ip, created_at__gte=timezone.now() - timedelta(hours=1)).count()
        if recent >= 5:
            messages.error(request, "Too many messages from your network in the last hour. Try again later.")
        elif form.is_valid():
            msg = form.save(commit=False)
            msg.ip_address = ip
            msg.save()
            messages.success(request, "Message sent. The system administrator will reply by e-mail.")
            return redirect("core:contact")
    return render(request, "public/contact.html", {"form": form})


# --------------------------------------------------------------------------- dashboards
def _status_counts(qs):
    return {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}


def _grade_chart(cadets):
    policy = active_policy()
    if not policy:
        return None
    counts = {r["band_label"]: r["n"] for r in DisciplineAssessment.objects.filter(
        cadet__in=cadets, is_current=True).values("band_label").annotate(n=Count("id"))}
    bands = list(policy.bands.all())
    return {"type": "doughnut", "labels": [b.label for b in bands],
            "datasets": [{"label": "Cadets", "data": [counts.get(b.label, 0) for b in bands],
                          "backgroundColor": [b.color for b in bands]}]}


def _trend(statements, months=6):
    today = timezone.localdate()
    start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    labels, data = [], []
    cur = start
    while cur <= today:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        labels.append(cur.strftime("%b"))
        data.append(statements.filter(incident_at__date__gte=cur, incident_at__date__lt=nxt).exclude(
            status__in=[S.DRAFT, S.WITHDRAWN]).count())
        cur = nxt
    return {"type": "bar", "legend": False, "labels": labels, "datasets": [{"label": "Statements", "data": data}]}


def _review_queue(user):
    from discipline.views import review_queue_qs

    return review_queue_qs(user)


@login_required
def dashboard(request):
    u = request.user
    ctx = {"role": u.role, "policy": active_policy(), "now": timezone.now()}
    overdue_days = get_setting("review_overdue_days")
    overdue_cut = timezone.now() - timedelta(days=overdue_days)
    if u.role == Role.ADMIN:
        cadets = Cadet.objects.filter(is_archived=False)
        stm = DisciplinaryStatement.objects.exclude(status=S.DRAFT)
        sc = _status_counts(stm)
        pending = stm.filter(status__in=[S.SUBMITTED, S.COMPANY_REVIEW])
        ctx.update({
            "active_cadets": cadets.filter(status=Cadet.Status.ACTIVE).count(),
            "active_users": User.objects.filter(is_active=True, is_suspended=False).count(),
            "inactive_users": User.objects.filter(Q(is_active=False) | Q(is_suspended=True)).count(),
            "staff_by_role": [(Role(r["role"]).label, r["n"]) for r in
                              User.objects.filter(is_active=True).values("role").annotate(n=Count("id")).order_by("role")],
            "org_counts": {"intakes": Intake.objects.filter(is_active=True).count(),
                           "companies": Company.objects.filter(is_active=True).count(),
                           "platoons": Platoon.objects.filter(is_active=True).count()},
            "pending": pending.count(), "overdue": pending.filter(last_transition_at__lt=overdue_cut).count(),
            "approved": sc.get(S.APPROVED, 0), "rejected": sc.get(S.REJECTED, 0),
            "failed_logins": LoginAttempt.objects.filter(successful=False,
                                                         created_at__gte=timezone.now() - timedelta(hours=24)).count(),
            "denied_events": AuditEvent.objects.filter(outcome=AuditEvent.Outcome.DENIED,
                                                       created_at__gte=timezone.now() - timedelta(days=7)).count(),
            "recent_activity": AuditEvent.objects.exclude(event_type__in=["cadet.viewed"])[:8],
            "chart_company": {"type": "bar", "legend": False,
                              "labels": [c.name for c in Company.objects.all()],
                              "datasets": [{"label": "Cadets", "data": [
                                  c.n for c in Company.objects.annotate(n=Count("cadets", filter=Q(
                                      cadets__is_archived=False)))]}]},
            "chart_intake": {"type": "doughnut", "labels": [i.code for i in Intake.objects.all()],
                             "datasets": [{"label": "Cadets", "data": [
                                 i.n for i in Intake.objects.annotate(n=Count("cadets", filter=Q(
                                     cadets__is_archived=False)))]}]},
            "chart_trend": _trend(DisciplinaryStatement.objects.all()),
            "chart_grades": _grade_chart(cadets),
        })
        template = "dashboards/admin.html"
    elif u.role == Role.INSTRUCTOR:
        mine = DisciplinaryStatement.objects.filter(submitted_by=u)
        sc = _status_counts(mine)
        ctx.update({"cadet_count": visible_cadets(u).count(), "counts": sc,
                    "in_review": sc.get(S.SUBMITTED, 0) + sc.get(S.COMPANY_REVIEW, 0),
                    "returned": mine.filter(status=S.RETURNED).select_related("cadet")[:5],
                    "recent": mine.select_related("cadet", "category").order_by("-updated_at")[:8]})
        template = "dashboards/instructor.html"
    elif u.role in (Role.PLATOON_COMMANDER, Role.COMPANY_COMMANDER):
        cadets = visible_cadets(u)
        stm = visible_statements(u)
        queue = _review_queue(u).order_by("last_transition_at")
        companies, platoons = unit_ids(u)
        recent_decisions = stm.filter(transitions__actor=u).distinct().order_by("-last_transition_at")[:6]
        decided = stm.filter(status__in=[S.APPROVED, S.REJECTED], decided_at__isnull=False, submitted_at__isnull=False)
        days = [(s.decided_at - s.submitted_at).total_seconds() / 86400 for s in decided[:200]]
        ctx.update({
            "units": list(Company.objects.filter(pk__in=companies)) + list(
                Platoon.objects.filter(pk__in=platoons).select_related("company")),
            "cadet_count": cadets.count(), "queue": queue[:8], "queue_count": queue.count(),
            "overdue": queue.filter(last_transition_at__lt=overdue_cut).count(),
            "counts": _status_counts(stm), "recent_decisions": recent_decisions,
            "turnaround": round(sum(days) / len(days), 1) if days else None,
            "chart_grades": _grade_chart(cadets), "chart_trend": _trend(stm),
            "flagged": DisciplineAssessment.objects.filter(cadet__in=cadets, is_current=True, requires_review=True)
            .select_related("cadet")[:6],
        })
        if u.role == Role.COMPANY_COMMANDER:
            per_platoon = Platoon.objects.filter(company_id__in=companies).annotate(
                approved=Count("statements", filter=Q(statements__status=S.APPROVED)),
                pending=Count("statements", filter=Q(statements__status__in=[S.SUBMITTED, S.COMPANY_REVIEW])),
                cadet_n=Count("cadets", filter=Q(cadets__is_archived=False), distinct=True))
            ctx["chart_platoons"] = {"type": "bar", "stacked": False, "labels": [p.name for p in per_platoon],
                                     "datasets": [{"label": "Approved", "data": [p.approved for p in per_platoon]},
                                                  {"label": "Pending", "data": [p.pending for p in per_platoon]}]}
        template = "dashboards/commander.html"
    elif u.role == Role.DOCTOR:
        from medical.models import MedicalRecord
        from .scoping import visible_medical_cadets

        recs = MedicalRecord.objects.filter(cadet__in=visible_medical_cadets(u))
        today = timezone.localdate()
        ctx.update({
            "cadet_count": visible_medical_cadets(u).count(),
            "open_count": recs.filter(status=MedicalRecord.Status.OPEN).count(),
            "follow_count": recs.filter(status=MedicalRecord.Status.FOLLOW_UP).count(),
            "overdue_follow": recs.filter(status=MedicalRecord.Status.FOLLOW_UP, follow_up_date__lt=today).count(),
            "follow_ups": recs.filter(status=MedicalRecord.Status.FOLLOW_UP).select_related("cadet")
            .order_by("follow_up_date")[:8],
            "recent": recs.filter(created_by=u).select_related("cadet")[:8], "today": today,
            "chart_fitness": {"type": "doughnut", "labels": [l for _, l in MedicalRecord.Fitness.choices],
                              "datasets": [{"label": "Records", "data": [
                                  recs.filter(fitness_status=v).count() for v, _ in MedicalRecord.Fitness.choices]}]},
        })
        template = "dashboards/doctor.html"
    else:  # auditor
        day = timezone.now() - timedelta(days=1)
        ctx.update({
            "events_24h": AuditEvent.objects.filter(created_at__gte=day).count(),
            "denied_7d": AuditEvent.objects.filter(outcome=AuditEvent.Outcome.DENIED,
                                                   created_at__gte=timezone.now() - timedelta(days=7)).count(),
            "failed_logins": AuditEvent.objects.filter(event_type="auth.login_failed", created_at__gte=day).count(),
            "exports_7d": AuditEvent.objects.filter(event_type__startswith="export.",
                                                    created_at__gte=timezone.now() - timedelta(days=7)).count(),
            "recent_denied": AuditEvent.objects.filter(outcome__in=["DENIED", "FAILURE"])[:10],
        })
        template = "dashboards/auditor.html"
    return render(request, template, ctx)


@login_required
def search(request):
    q = (request.GET.get("q") or "").strip()[:80]
    cadets, statements = [], []
    if len(q) >= 2:
        cadets = visible_cadets(request.user).filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(cadet_number__icontains=q))[:20]
        statements = visible_statements(request.user).filter(
            Q(reference__icontains=q) | Q(title__icontains=q))[:20]
    return render(request, "core/search.html", {"q": q, "cadets": cadets, "statements": statements})


# --------------------------------------------------------------------------- settings
@require_perm(Perm.SETTINGS_MANAGE)
def settings_view(request):
    items = list(ApplicationSetting.objects.all())
    errors = {}
    if request.method == "POST":
        changed = {}
        for s in items:
            raw = request.POST.get(s.key, "")
            if s.value_type == s.ValueType.BOOL:
                new = "true" if raw == "on" else "false"
            elif s.value_type == s.ValueType.INT:
                try:
                    n = int(raw)
                    if not 0 < n <= 365:
                        raise ValueError
                    new = str(n)
                except ValueError:
                    errors[s.key] = "Enter a whole number between 1 and 365."
                    continue
            else:
                new = raw.strip()[:255]
                if not new:
                    errors[s.key] = "This value cannot be empty."
                    continue
            if new != s.value:
                changed[s.key] = {"from": s.value, "to": new}
                s.value, s.updated_by = new, request.user
                s.save()
        if not errors:
            if changed:
                log_event("settings.updated", request=request, metadata=changed)
                messages.success(request, "Settings saved.")
            else:
                messages.info(request, "No changes.")
            return redirect("core:settings")
    return render(request, "core/settings.html", {"items": items, "errors": errors})


@require_perm(Perm.SETTINGS_MANAGE)
def contact_messages(request):
    page = Paginator(ContactMessage.objects.all(), 20).get_page(request.GET.get("page"))
    return render(request, "core/contact_messages.html", {"page_obj": page})


@require_POST
@require_perm(Perm.SETTINGS_MANAGE)
def contact_message_handled(request, pk):
    ContactMessage.objects.filter(pk=pk).update(is_handled=True)
    messages.success(request, "Marked as handled.")
    return redirect("core:contact_messages")


# --------------------------------------------------------------------------- errors
def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
