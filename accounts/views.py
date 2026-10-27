from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from audit.services import client_ip, log_event
from cadets.models import StaffAssignment
from core.decorators import require_perm
from core.permissions import PERMISSION_LABELS, ROLE_PERMISSIONS, Perm, Role

from . import services
from .forms import (LoginForm, PermissionGrantForm, ProfileForm, SuspendForm, UnitAssignmentForm,
                    UserCreateForm, UserEditForm, UserFilterForm)
from .models import PermissionGrant, User


# --------------------------------------------------------------------------- authentication
def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST":
        email = (request.POST.get("username") or "").strip().lower()
        ip = client_ip(request)
        if services.is_locked_out(email, ip):
            services.log_login(request, email, False, "locked_out")
            messages.error(request, f"Too many failed attempts. Try again in {settings.LOGIN_LOCKOUT_MINUTES} minutes "
                                    "or reset your password.")
            return render(request, "accounts/login.html", {"form": LoginForm(request)}, status=429)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            request.session.cycle_key()
            services.record_login_attempt(email, ip, True)
            services.log_login(request, email, True)
            next_url = request.GET.get("next", "")
            from django.utils.http import url_has_allowed_host_and_scheme

            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
                return redirect(next_url)
            return redirect("core:dashboard")
        services.record_login_attempt(email, ip, False)
        services.log_login(request, email, False)
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        log_event("auth.logout", request=request)
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")


class PasswordResetView(auth_views.PasswordResetView):
    """Always shows the same response whether or not the email exists."""

    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/emails/password_reset_email.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        log_event("auth.password_reset_requested", request=self.request,
                  metadata={"email": form.cleaned_data.get("email", "")})
        return super().form_valid(form)


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_event("auth.password_reset_completed", request=self.request, actor=form.user, obj=form.user)
        return response


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_event("auth.password_changed", request=self.request, obj=self.request.user)
        messages.success(self.request, "Your password was changed.")
        return response


# --------------------------------------------------------------------------- own profile
@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_event("account.profile_updated", request=request, obj=request.user, metadata={"changed": form.changed_data})
        messages.success(request, "Profile saved.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "form": form,
        "assignments": request.user.unit_assignments.filter(is_active=True).select_related("company", "platoon"),
        "grants": request.user.permission_grants.active(),
        "perm_labels": [PERMISSION_LABELS[p] for p in sorted(request.user.effective_permissions())],
        "recent_logins": request.user.audit_events.filter(event_type="auth.login")[:5],
    })


# --------------------------------------------------------------------------- user administration
@require_perm(Perm.USERS_VIEW)
def user_list(request):
    f = UserFilterForm(request.GET or None)
    qs = User.objects.all().order_by("last_name", "first_name")
    if f.is_valid():
        q = f.cleaned_data["q"]
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
                           | Q(service_number__icontains=q))
        if f.cleaned_data["role"]:
            qs = qs.filter(role=f.cleaned_data["role"])
        status = f.cleaned_data["status"]
        if status == "active":
            qs = qs.filter(is_active=True, is_suspended=False)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        elif status == "suspended":
            qs = qs.filter(is_suspended=True)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "accounts/user_list.html", {"page_obj": page, "filter": f, "roles": Role.choices})


@require_perm(Perm.USERS_MANAGE)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = services.create_user(request, form)
        link = services.send_invitation(request, user)
        messages.success(request, f"Account created for {user.email}. A single-use invitation link was e-mailed.")
        if settings.DEBUG:
            messages.info(request, f"Development only — invitation link: {link}")
        return redirect("accounts:user_detail", pk=user.pk)
    return render(request, "accounts/user_form.html", {"form": form, "is_new": True})


@require_perm(Perm.USERS_VIEW)
def user_detail(request, pk):
    target = get_object_or_404(User, pk=pk)
    return render(request, "accounts/user_detail.html", {
        "target": target,
        "assignments": target.unit_assignments.select_related("company", "platoon", "assigned_by"),
        "grants": target.permission_grants.select_related("granted_by", "revoked_by"),
        "role_perms": sorted(PERMISSION_LABELS[p] for p in ROLE_PERMISSIONS.get(target.role, [])),
        "grant_form": PermissionGrantForm(), "unit_form": UnitAssignmentForm(), "suspend_form": SuspendForm(),
        "events": target.audit_events.all()[:10],
    })


@require_perm(Perm.USERS_MANAGE)
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    original_role = target.role
    form = UserEditForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        if target.pk == request.user.pk and form.cleaned_data["role"] != Role.ADMIN:
            form.add_error("role", "You cannot remove your own administrator role.")
        else:
            services.update_user(request, target, form, original_role)
            messages.success(request, "User details saved.")
            return redirect("accounts:user_detail", pk=target.pk)
    return render(request, "accounts/user_form.html", {"form": form, "target": target, "is_new": False})


def _action(request, fn, *args, success=""):
    try:
        fn(request, *args)
        messages.success(request, success)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))


@require_POST
@require_perm(Perm.USERS_MANAGE)
def user_set_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    active = request.POST.get("active") == "1"
    _action(request, services.set_active, target, active,
            success=f"Account {'activated' if active else 'deactivated'}.")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.USERS_MANAGE)
def user_suspend(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = SuspendForm(request.POST)
    if form.is_valid():
        _action(request, services.suspend, target, form.cleaned_data["reason"], success="Account suspended.")
    else:
        messages.error(request, "A suspension reason of at least 5 characters is required.")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.USERS_MANAGE)
def user_reinstate(request, pk):
    target = get_object_or_404(User, pk=pk)
    _action(request, services.reinstate, target, success="Account reinstated.")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.USERS_MANAGE)
def user_resend_invite(request, pk):
    target = get_object_or_404(User, pk=pk)
    link = services.send_invitation(request, target)
    messages.success(request, "A new single-use set-password link was e-mailed.")
    if settings.DEBUG:
        messages.info(request, f"Development only — link: {link}")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.USERS_MANAGE)
def user_grant(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = PermissionGrantForm(request.POST)
    if form.is_valid():
        _action(request, services.grant_permission, target, form.cleaned_data["permission"],
                form.cleaned_data["reason"], form.cleaned_data["expires_at"], success="Permission granted.")
    else:
        messages.error(request, "Choose a permission and give a reason (min. 5 characters).")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.USERS_MANAGE)
def user_revoke(request, pk, grant_id):
    grant = get_object_or_404(PermissionGrant, pk=grant_id, user_id=pk, revoked_at__isnull=True)
    services.revoke_permission(request, grant)
    messages.success(request, "Permission revoked.")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.ORG_MANAGE)
def user_assign(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UnitAssignmentForm(request.POST)
    if form.is_valid():
        _action(request, services.assign_unit, target, form.cleaned_data["company"], form.cleaned_data["platoon"],
                success="Unit assignment added.")
    else:
        messages.error(request, " ".join(form.non_field_errors()) or "Invalid assignment.")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm(Perm.ORG_MANAGE)
def user_unassign(request, pk, assignment_id):
    a = get_object_or_404(StaffAssignment, pk=assignment_id, user_id=pk, is_active=True)
    services.end_assignment(request, a)
    messages.success(request, "Assignment ended.")
    return redirect("accounts:user_detail", pk=pk)


@require_perm(Perm.USERS_VIEW)
def permission_matrix(request):
    roles = list(Role)
    rows = [{"code": code, "label": label, "cells": [code in ROLE_PERMISSIONS[r] for r in roles]}
            for code, label in PERMISSION_LABELS.items()]
    return render(request, "accounts/matrix.html", {"roles": roles, "rows": rows})
