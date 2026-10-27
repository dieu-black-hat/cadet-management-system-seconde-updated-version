from datetime import timedelta

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from audit.models import AuditEvent
from audit.services import log_event
from cadets.models import StaffAssignment
from notifications.models import Notification
from notifications.services import notify

from .models import LoginAttempt, PermissionGrant, User


# --------------------------------------------------------------------------- login throttling
def is_locked_out(email: str, ip: str | None) -> bool:
    window = timezone.now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    email_failures = LoginAttempt.objects.filter(email=email.lower(), successful=False, created_at__gte=window).count()
    ip_failures = LoginAttempt.objects.filter(ip_address=ip, successful=False, created_at__gte=window).count() if ip else 0
    return email_failures >= settings.LOGIN_MAX_FAILURES or ip_failures >= settings.LOGIN_MAX_FAILURES * 4


def record_login_attempt(email: str, ip: str | None, success: bool) -> None:
    LoginAttempt.objects.create(email=email.lower()[:254], ip_address=ip, successful=success)
    if success:
        # A successful login clears the failure counter for this account
        LoginAttempt.objects.filter(email=email.lower(), successful=False).delete()


# --------------------------------------------------------------------------- invitations
def invitation_link(request, user) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    return request.build_absolute_uri(path)


def send_invitation(request, user) -> str:
    link = invitation_link(request, user)
    send_mail(
        "Your Officer Cadet Management System account",
        f"Hello {user.get_full_name()},\n\nAn account has been created for you. "
        f"Set your password using this single-use link (valid for {settings.PASSWORD_RESET_TIMEOUT // 3600} hour(s)):\n\n{link}\n",
        settings.DEFAULT_FROM_EMAIL, [user.email],
    )
    log_event("account.invitation_sent", request=request, obj=user)
    return link


@transaction.atomic
def create_user(request, form) -> User:
    user = form.save(commit=False)
    user.set_unusable_password()  # no password is ever chosen or emailed by an administrator
    user.created_by = request.user
    user.save()
    log_event("account.created", request=request, obj=user, metadata={"email": user.email, "role": user.role})
    return user


def update_user(request, user, form, original_role):
    user = form.save()
    meta = {"changed": form.changed_data}
    if "role" in form.changed_data:
        meta.update({"old_role": original_role, "new_role": user.role})
        notify([user], Notification.Kind.ACCOUNT, "Your role was changed",
               message=f"New role: {user.get_role_display()}", link="/accounts/profile/")
    log_event("account.updated", request=request, obj=user, metadata=meta)
    return user


def _guard_self(request, user):
    if user.pk == request.user.pk:
        raise ValidationError("You cannot change the status of your own account.")


@transaction.atomic
def set_active(request, user, active: bool):
    _guard_self(request, user)
    user.is_active = active
    user.save(update_fields=["is_active", "updated_at"])
    log_event("account.activated" if active else "account.deactivated", request=request, obj=user)


@transaction.atomic
def suspend(request, user, reason: str):
    _guard_self(request, user)
    user.is_suspended = True
    user.suspended_reason = reason
    user.suspended_at = timezone.now()
    user.save(update_fields=["is_suspended", "suspended_reason", "suspended_at", "updated_at"])
    log_event("account.suspended", request=request, obj=user, metadata={"reason": reason})


@transaction.atomic
def reinstate(request, user):
    user.is_suspended = False
    user.suspended_reason = ""
    user.suspended_at = None
    user.save(update_fields=["is_suspended", "suspended_reason", "suspended_at", "updated_at"])
    log_event("account.reinstated", request=request, obj=user)
    notify([user], Notification.Kind.ACCOUNT, "Your account was reinstated", link="/accounts/profile/")


@transaction.atomic
def grant_permission(request, user, permission, reason, expires_at=None):
    if user.permission_grants.filter(permission=permission, revoked_at__isnull=True).exists():
        raise ValidationError("This permission is already granted.")
    grant = PermissionGrant.objects.create(user=user, permission=permission, reason=reason,
                                           expires_at=expires_at, granted_by=request.user)
    log_event("permission.granted", request=request, obj=user, metadata={"permission": permission, "reason": reason})
    notify([user], Notification.Kind.ACCOUNT, "A permission was granted to you", link="/accounts/profile/")
    return grant


@transaction.atomic
def revoke_permission(request, grant):
    grant.revoked_at = timezone.now()
    grant.revoked_by = request.user
    grant.save(update_fields=["revoked_at", "revoked_by"])
    log_event("permission.revoked", request=request, obj=grant.user, metadata={"permission": grant.permission})


@transaction.atomic
def assign_unit(request, user, company=None, platoon=None):
    filt = {"user": user, "is_active": True}
    filt.update({"company": company} if company else {"platoon": platoon})
    if StaffAssignment.objects.filter(**filt).exists():
        raise ValidationError("This assignment already exists.")
    a = StaffAssignment.objects.create(user=user, company=company, platoon=platoon, assigned_by=request.user)
    log_event("assignment.created", request=request, obj=user, metadata={"unit": a.unit_label})
    return a


@transaction.atomic
def end_assignment(request, assignment):
    assignment.is_active = False
    assignment.ended_at = timezone.now()
    assignment.save(update_fields=["is_active", "ended_at"])
    log_event("assignment.ended", request=request, obj=assignment.user, metadata={"unit": assignment.unit_label})


def log_login(request, email, success, reason=""):
    log_event("auth.login" if success else "auth.login_failed", request=request,
              outcome=AuditEvent.Outcome.SUCCESS if success else AuditEvent.Outcome.FAILURE,
              metadata={"email": email, **({"reason": reason} if reason else {})})
