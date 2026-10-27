# Roles and permissions

Permissions are checked on the server for every request (`core/decorators.require_perm`). The same
matrix is shown in the app under **Administration → Permission matrix**. Administrators can grant an
individual user an extra permission (with a reason and optional expiry); grants are audited.

| Permission | Admin | Instructor | Platoon cdr | Company cdr | Doctor | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| View / manage user accounts | ✔ / ✔ | | | | | ✔ / – |
| Manage intakes, companies, platoons, staff assignments | ✔ | | | | | |
| View cadets (within scope) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Register / edit / assign / import / export cadets | ✔ | | | | | |
| View statements (within scope) | ✔¹ | own | ✔ | ✔ | | ✔¹ |
| Create & submit statements | | ✔ | | | | |
| Platoon-level review | | | ✔ | | | |
| Company-level review | | | | ✔ | | |
| View grades & policy | ✔ | ✔ | ✔ | ✔ | | ✔ |
| Configure grading policy | ✔ | | | | | |
| Manual assessment override | ✔ | | | ✔ | | |
| Full medical records & documents | | | | | ✔ | |
| Create / update medical records | | | | | ✔ | |
| Released fitness summary only | ✔ | | ✔ | ✔ | ✔ | |
| Reports / exports | ✔ / ✔ | | ✔ / – | ✔ / ✔ | | ✔ / ✔ |
| Audit trail | ✔ | | | | | ✔ |
| Application settings | ✔ | | | | | |

¹ Administrators and auditors never see other users' unsubmitted drafts.

## Scope rules

| Role | Records visible |
|---|---|
| Administrator, Auditor | Whole institution |
| Company commander, Instructor, Doctor | Cadets in their assigned companies (and/or platoons) |
| Platoon commander | Cadets in their assigned platoons |

Additional rules: the author of a statement can never review it; a reviewer can only act on statements
routed to their own unit and at the matching stage; drafts are visible to their author only.
