"""Helpers for writing audit events. Never pass secrets or medical content in metadata."""
from __future__ import annotations

from typing import Any

from .models import AuditEvent

SENSITIVE_KEYS = {"password", "password1", "password2", "new_password1", "new_password2", "token", "secret",
                  "csrfmiddlewaretoken", "clinical_notes", "session"}


def client_ip(request) -> str | None:
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")


def _clean(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    return {k: ("[redacted]" if k.lower() in SENSITIVE_KEYS else v) for k, v in meta.items()}


def log_event(event_type: str, *, request=None, actor=None, obj=None, object_type: str = "",
              object_id: str | int = "", outcome: str = AuditEvent.Outcome.SUCCESS,
              metadata: dict[str, Any] | None = None) -> AuditEvent:
    if actor is None and request is not None and getattr(request, "user", None) is not None \
            and request.user.is_authenticated:
        actor = request.user
    if obj is not None:
        object_type = object_type or obj.__class__.__name__
        object_id = object_id or obj.pk
    return AuditEvent.objects.create(
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        actor_email=getattr(actor, "email", "") or "",
        actor_role=getattr(actor, "role", "") or "",
        event_type=event_type,
        object_type=object_type,
        object_id=str(object_id or ""),
        outcome=outcome,
        metadata=_clean(metadata),
        ip_address=client_ip(request),
    )
