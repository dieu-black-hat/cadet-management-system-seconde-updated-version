from django.conf import settings
from django.urls import reverse

from .models import get_setting
from .permissions import Perm


def _nav_for(user):
    """Navigation is built from permissions; the server still checks every view independently."""
    p = user.has_ocms_perm
    sections = [
        ("Overview", [
            ("Dashboard", "core:dashboard", "bi-speedometer2", True),
            ("Notifications", "notifications:list", "bi-bell", True),
        ]),
        ("Cadets", [
            ("Cadet directory", "cadets:list", "bi-people", p(Perm.CADETS_VIEW)),
            ("Register cadet", "cadets:create", "bi-person-plus", p(Perm.CADETS_CREATE)),
            ("Import / export", "cadets:import", "bi-filetype-csv", p(Perm.CADETS_IMPORT)),
        ]),
        ("Discipline", [
            ("My statements", "discipline:mine", "bi-journal-text", p(Perm.STATEMENTS_CREATE)),
            ("New statement", "discipline:create", "bi-journal-plus", p(Perm.STATEMENTS_CREATE)),
            ("Review queue", "discipline:queue", "bi-inbox",
             p(Perm.STATEMENTS_REVIEW_PLATOON) or p(Perm.STATEMENTS_REVIEW_COMPANY)),
            ("All statements", "discipline:list", "bi-collection", p(Perm.STATEMENTS_VIEW)),
            ("Grading policy", "discipline:policy_list", "bi-sliders", p(Perm.GRADING_VIEW)),
        ]),
        ("Medical", [
            ("Medical workspace", "medical:list", "bi-heart-pulse", p(Perm.MEDICAL_VIEW_FULL)),
            ("New medical record", "medical:create", "bi-file-earmark-medical", p(Perm.MEDICAL_EDIT)),
        ]),
        ("Reports", [
            ("Reports & analytics", "reports:index", "bi-bar-chart-line", p(Perm.REPORTS_VIEW)),
            ("Audit trail", "audit:list", "bi-shield-check", p(Perm.AUDIT_VIEW)),
        ]),
        ("Administration", [
            ("Users & roles", "accounts:user_list", "bi-person-badge", p(Perm.USERS_VIEW)),
            ("Organisation", "cadets:org", "bi-diagram-3", p(Perm.ORG_MANAGE)),
            ("Permission matrix", "accounts:matrix", "bi-grid-3x3-gap", p(Perm.USERS_VIEW)),
            ("System settings", "core:settings", "bi-gear", p(Perm.SETTINGS_MANAGE)),
            ("Contact messages", "core:contact_messages", "bi-envelope", p(Perm.SETTINGS_MANAGE)),
        ]),
    ]
    out = []
    for title, items in sections:
        visible = [{"label": label, "url": reverse(name), "name": name, "icon": icon}
                   for label, name, icon, ok in items if ok]
        if visible:
            out.append({"title": title, "items": visible})
    return out


def app_context(request):
    ctx = {
        "INSTITUTION_NAME": settings.INSTITUTION_NAME,
        "SYNTHETIC_DATA_BANNER": settings.SYNTHETIC_DATA_BANNER,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        try:
            ctx["INSTITUTION_NAME"] = get_setting("institution_name")
        except Exception:  # pragma: no cover
            pass
        ctx["nav_sections"] = _nav_for(user)
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
        ctx["recent_notifications"] = user.notifications.all()[:5]
        ctx["current_url_name"] = (
            f"{request.resolver_match.namespace}:{request.resolver_match.url_name}"
            if request.resolver_match and request.resolver_match.namespace else ""
        )
    return ctx
