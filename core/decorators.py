from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from audit.models import AuditEvent
from audit.services import log_event


def deny(request, reason: str, **meta):
    """Record an authorization failure and raise 403."""
    log_event("authz.denied", request=request, outcome=AuditEvent.Outcome.DENIED,
              metadata={"path": request.path, "reason": reason, **meta})
    raise PermissionDenied(reason)


def require_perm(*codes, any_of=False):
    """View decorator: login required + OCMS permission code(s) checked on the server."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            checks = [request.user.has_ocms_perm(c) for c in codes]
            ok = any(checks) if any_of else all(checks)
            if not ok:
                deny(request, "missing permission", required=list(codes))
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
