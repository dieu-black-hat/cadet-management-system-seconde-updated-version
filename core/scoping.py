"""
Organisational scoping: every list, detail view, statistic and export is
filtered through these functions so a user only ever sees records inside the
units they are assigned to.
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from .permissions import GLOBAL_SCOPE_ROLES, Perm, Role


def has_global_scope(user) -> bool:
    return user.is_authenticated and user.role in GLOBAL_SCOPE_ROLES


def unit_ids(user) -> tuple[set[int], set[int]]:
    """Return (company_ids, platoon_ids) the user is actively assigned to."""
    cache = getattr(user, "_ocms_units", None)
    if cache is None:
        from cadets.models import StaffAssignment

        companies, platoons = set(), set()
        for company_id, platoon_id in StaffAssignment.objects.filter(user=user, is_active=True).values_list(
            "company_id", "platoon_id"
        ):
            if company_id:
                companies.add(company_id)
            if platoon_id:
                platoons.add(platoon_id)
        cache = (companies, platoons)
        user._ocms_units = cache
    return cache


def cadet_scope_q(user, prefix: str = "") -> Q:
    """Q object restricting cadets (optionally via a relation prefix) to the user's units."""
    if has_global_scope(user):
        return Q()
    companies, platoons = unit_ids(user)
    if not companies and not platoons:
        return Q(pk__in=[])
    q = Q()
    if companies:
        q |= Q(**{f"{prefix}company_id__in": companies})
    if platoons:
        q |= Q(**{f"{prefix}platoon_id__in": platoons})
    return q


def visible_cadets(user) -> QuerySet:
    from cadets.models import Cadet

    if not user.is_authenticated or not user.has_ocms_perm(Perm.CADETS_VIEW):
        return Cadet.objects.none()
    qs = Cadet.objects.select_related("intake", "company", "platoon")
    if has_global_scope(user):
        return qs
    return qs.filter(cadet_scope_q(user)).filter(is_archived=False)


def can_view_cadet(user, cadet) -> bool:
    return visible_cadets(user).filter(pk=cadet.pk).exists()


def visible_statements(user) -> QuerySet:
    """Statements visible to a user, respecting role and organisational scope."""
    from discipline.models import DisciplinaryStatement as S

    if not user.is_authenticated or not user.has_ocms_perm(Perm.STATEMENTS_VIEW):
        return S.objects.none()
    qs = S.objects.select_related("cadet", "category", "submitted_by", "platoon", "company")
    if has_global_scope(user):
        # Administrators/auditors do not see other people's private drafts.
        return qs.exclude(status=S.Status.DRAFT)
    companies, platoons = unit_ids(user)
    own = Q(submitted_by=user)
    if user.role == Role.INSTRUCTOR:
        return qs.filter(own)
    scoped = Q(pk__in=[])
    if user.has_ocms_perm(Perm.STATEMENTS_REVIEW_PLATOON) or user.role == Role.PLATOON_COMMANDER:
        if platoons:
            scoped |= Q(platoon_id__in=platoons)
        if companies:
            scoped |= Q(company_id__in=companies)
    if user.has_ocms_perm(Perm.STATEMENTS_REVIEW_COMPANY) or user.role == Role.COMPANY_COMMANDER:
        if companies:
            scoped |= Q(company_id__in=companies)
    return qs.filter(own | (scoped & ~Q(status=S.Status.DRAFT)))


def visible_medical_cadets(user) -> QuerySet:
    """Cadets whose medical records the user may open (full records)."""
    if not user.is_authenticated or not user.has_ocms_perm(Perm.MEDICAL_VIEW_FULL):
        from cadets.models import Cadet

        return Cadet.objects.none()
    return visible_cadets(user)
