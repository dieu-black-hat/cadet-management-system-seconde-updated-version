from django import template
from django.utils.http import urlencode

register = template.Library()


@register.filter
def has_perm(user, code):
    """Display helper only — views always re-check permissions on the server."""
    return bool(user and user.is_authenticated and user.has_ocms_perm(code))


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Return the current query string with the given keys replaced (used for pagination & sorting)."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + urlencode(sorted(params.lists()), doseq=True) if params else "?"


@register.inclusion_tag("components/grade.html")
def grade(assessment, compact=False, base=100):
    pct = 0
    if assessment is not None:
        base = assessment.policy.base_score or base
        pct = max(0, min(100, round(assessment.score * 100 / base)))
    return {"a": assessment, "compact": compact, "pct": pct}


@register.inclusion_tag("components/status_badge.html")
def status_badge(statement):
    icons = {"DRAFT": "bi-pencil", "SUBMITTED": "bi-hourglass-split", "COMPANY_REVIEW": "bi-hourglass-bottom",
             "APPROVED": "bi-patch-check", "REJECTED": "bi-x-octagon", "RETURNED": "bi-arrow-return-left",
             "WITHDRAWN": "bi-slash-circle"}
    return {"status": statement.status, "label": statement.get_status_display(), "icon": icons.get(statement.status, "bi-dot")}


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def role_label(value):
    from core.permissions import Role

    try:
        return Role(value).label
    except ValueError:
        return value
