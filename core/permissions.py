"""
Role and permission matrix.

Authorization is deny-by-default:
  * a user holds exactly one primary role;
  * each role maps to an explicit set of permission codes (ROLE_PERMISSIONS);
  * an administrator may grant additional permission codes to an individual
    user (accounts.PermissionGrant), optionally with an expiry date;
  * record-level access is further limited by organisational scope
    (see core.scoping) — a permission alone never grants access to every cadet.
"""
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "System Administrator"
    INSTRUCTOR = "INSTRUCTOR", "Instructor"
    PLATOON_COMMANDER = "PLATOON_CDR", "Platoon Commander"
    COMPANY_COMMANDER = "COMPANY_CDR", "Company Commander"
    DOCTOR = "DOCTOR", "Doctor / Medical Officer"
    AUDITOR = "AUDITOR", "Auditor (read-only)"


class Perm:
    USERS_VIEW = "users.view"
    USERS_MANAGE = "users.manage"
    ORG_MANAGE = "org.manage"
    CADETS_VIEW = "cadets.view"
    CADETS_CREATE = "cadets.create"
    CADETS_EDIT = "cadets.edit"
    CADETS_ASSIGN = "cadets.assign"
    CADETS_IMPORT = "cadets.import"
    CADETS_EXPORT = "cadets.export"
    STATEMENTS_VIEW = "statements.view"
    STATEMENTS_CREATE = "statements.create"
    STATEMENTS_REVIEW_PLATOON = "statements.review_platoon"
    STATEMENTS_REVIEW_COMPANY = "statements.review_company"
    GRADING_VIEW = "grading.view"
    GRADING_MANAGE = "grading.manage"
    ASSESSMENT_OVERRIDE = "assessment.override"
    MEDICAL_VIEW_FULL = "medical.view_full"
    MEDICAL_EDIT = "medical.edit"
    MEDICAL_VIEW_SUMMARY = "medical.view_summary"
    REPORTS_VIEW = "reports.view"
    REPORTS_EXPORT = "reports.export"
    AUDIT_VIEW = "audit.view"
    SETTINGS_MANAGE = "settings.manage"


PERMISSION_LABELS = {
    Perm.USERS_VIEW: "View user accounts",
    Perm.USERS_MANAGE: "Create / edit / deactivate user accounts",
    Perm.ORG_MANAGE: "Manage intakes, companies, platoons & staff assignments",
    Perm.CADETS_VIEW: "View cadets within scope",
    Perm.CADETS_CREATE: "Register cadets",
    Perm.CADETS_EDIT: "Edit cadet records",
    Perm.CADETS_ASSIGN: "Assign cadets to intakes, companies & platoons",
    Perm.CADETS_IMPORT: "Import cadet records (CSV)",
    Perm.CADETS_EXPORT: "Export cadet records",
    Perm.STATEMENTS_VIEW: "View disciplinary statements within scope",
    Perm.STATEMENTS_CREATE: "Create & submit disciplinary statements",
    Perm.STATEMENTS_REVIEW_PLATOON: "Platoon-level statement review",
    Perm.STATEMENTS_REVIEW_COMPANY: "Company-level statement review",
    Perm.GRADING_VIEW: "View discipline grades & policy legend",
    Perm.GRADING_MANAGE: "Configure grading policies",
    Perm.ASSESSMENT_OVERRIDE: "Record manual assessment overrides",
    Perm.MEDICAL_VIEW_FULL: "View full medical records & documents",
    Perm.MEDICAL_EDIT: "Create / update medical records",
    Perm.MEDICAL_VIEW_SUMMARY: "View approved fitness summaries only",
    Perm.REPORTS_VIEW: "View reports",
    Perm.REPORTS_EXPORT: "Export reports (CSV / PDF)",
    Perm.AUDIT_VIEW: "View audit trail",
    Perm.SETTINGS_MANAGE: "Manage application settings",
}

ALL_PERMISSIONS = tuple(PERMISSION_LABELS.keys())

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.ADMIN: frozenset({
        Perm.USERS_VIEW, Perm.USERS_MANAGE, Perm.ORG_MANAGE,
        Perm.CADETS_VIEW, Perm.CADETS_CREATE, Perm.CADETS_EDIT, Perm.CADETS_ASSIGN,
        Perm.CADETS_IMPORT, Perm.CADETS_EXPORT,
        Perm.STATEMENTS_VIEW, Perm.GRADING_VIEW, Perm.GRADING_MANAGE, Perm.ASSESSMENT_OVERRIDE,
        Perm.MEDICAL_VIEW_SUMMARY, Perm.REPORTS_VIEW, Perm.REPORTS_EXPORT,
        Perm.AUDIT_VIEW, Perm.SETTINGS_MANAGE,
    }),
    Role.INSTRUCTOR: frozenset({
        Perm.CADETS_VIEW, Perm.STATEMENTS_VIEW, Perm.STATEMENTS_CREATE, Perm.GRADING_VIEW,
    }),
    Role.PLATOON_COMMANDER: frozenset({
        Perm.CADETS_VIEW, Perm.STATEMENTS_VIEW, Perm.STATEMENTS_REVIEW_PLATOON,
        Perm.GRADING_VIEW, Perm.MEDICAL_VIEW_SUMMARY, Perm.REPORTS_VIEW,
    }),
    Role.COMPANY_COMMANDER: frozenset({
        Perm.CADETS_VIEW, Perm.STATEMENTS_VIEW, Perm.STATEMENTS_REVIEW_COMPANY,
        Perm.GRADING_VIEW, Perm.ASSESSMENT_OVERRIDE, Perm.MEDICAL_VIEW_SUMMARY,
        Perm.REPORTS_VIEW, Perm.REPORTS_EXPORT,
    }),
    Role.DOCTOR: frozenset({
        Perm.CADETS_VIEW, Perm.MEDICAL_VIEW_FULL, Perm.MEDICAL_EDIT, Perm.MEDICAL_VIEW_SUMMARY,
    }),
    Role.AUDITOR: frozenset({
        Perm.USERS_VIEW, Perm.CADETS_VIEW, Perm.STATEMENTS_VIEW, Perm.GRADING_VIEW,
        Perm.REPORTS_VIEW, Perm.REPORTS_EXPORT, Perm.AUDIT_VIEW,
    }),
}

# Roles whose organisational scope is the whole institution.
GLOBAL_SCOPE_ROLES = frozenset({Role.ADMIN, Role.AUDITOR})


def role_permissions(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())
