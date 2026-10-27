import csv
import io
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import log_event

from .models import Cadet, CadetAssignmentHistory, Company, Intake, Platoon

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection in exported cells."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


@transaction.atomic
def create_cadet(request, form) -> Cadet:
    cadet = form.save(commit=False)
    cadet.created_by = request.user
    cadet.updated_by = request.user
    cadet.full_clean()
    cadet.save()
    CadetAssignmentHistory.objects.create(
        cadet=cadet, to_intake=cadet.intake, to_company=cadet.company, to_platoon=cadet.platoon,
        reason="Initial registration", changed_by=request.user,
    )
    log_event("cadet.created", request=request, obj=cadet, metadata={"cadet_number": cadet.cadet_number})
    from discipline.grading import recalculate

    recalculate(cadet, actor=request.user, trigger="registration")
    return cadet


@transaction.atomic
def update_cadet(request, form) -> Cadet:
    cadet = form.save(commit=False)
    cadet.updated_by = request.user
    cadet.full_clean()
    cadet.save()
    log_event("cadet.updated", request=request, obj=cadet, metadata={"changed": form.changed_data})
    return cadet


@transaction.atomic
def reassign(request, cadet: Cadet, intake, company, platoon, reason: str) -> Cadet:
    cadet = Cadet.objects.select_for_update().get(pk=cadet.pk)
    if (cadet.intake_id, cadet.company_id, cadet.platoon_id) == (
            intake.pk, getattr(company, "pk", None), getattr(platoon, "pk", None)):
        raise ValidationError("The cadet is already assigned to these units.")
    CadetAssignmentHistory.objects.create(
        cadet=cadet, from_intake=cadet.intake, to_intake=intake, from_company=cadet.company, to_company=company,
        from_platoon=cadet.platoon, to_platoon=platoon, reason=reason, changed_by=request.user,
    )
    before = {"intake": str(cadet.intake), "company": str(cadet.company or ""), "platoon": str(cadet.platoon or "")}
    cadet.intake, cadet.company, cadet.platoon = intake, company, platoon
    cadet.updated_by = request.user
    cadet.full_clean()
    cadet.save()
    log_event("cadet.reassigned", request=request, obj=cadet, metadata={
        "before": before, "after": {"intake": str(intake), "company": str(company or ""), "platoon": str(platoon or "")},
        "reason": reason})
    return cadet


@transaction.atomic
def set_archived(request, cadet: Cadet, archived: bool) -> None:
    cadet.is_archived = archived
    if archived and cadet.status == Cadet.Status.ACTIVE:
        cadet.status = Cadet.Status.INACTIVE
    cadet.updated_by = request.user
    cadet.save(update_fields=["is_archived", "status", "updated_by", "updated_at"])
    log_event("cadet.archived" if archived else "cadet.restored", request=request, obj=cadet)


REQUIRED_COLUMNS = ["cadet_number", "first_name", "last_name", "gender", "intake_code", "company_code",
                    "platoon_code", "admission_date", "status"]


def import_csv(request, uploaded) -> tuple[int, list[str]]:
    """All-or-nothing import. Returns (created_count, errors)."""
    try:
        text = uploaded.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return 0, ["The file is not valid UTF-8 text."]
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        return 0, [f"Missing column(s): {', '.join(missing)}."]
    intakes = {i.code.upper(): i for i in Intake.objects.all()}
    companies = {c.code.upper(): c for c in Company.objects.all()}
    platoons = {(p.company.code.upper(), p.code.upper()): p for p in Platoon.objects.select_related("company")}
    statuses = {s.upper() for s in Cadet.Status.values}
    errors, rows, seen = [], [], set()
    for n, row in enumerate(reader, start=2):
        if n > 2001:
            errors.append("Import is limited to 2,000 rows per file.")
            break
        r = {k: (v or "").strip() for k, v in row.items() if k}
        num = r["cadet_number"].upper()
        problems = []
        if not num:
            problems.append("cadet_number is required")
        elif num in seen or Cadet.objects.filter(cadet_number=num).exists():
            problems.append(f"duplicate cadet_number {num}")
        seen.add(num)
        if not r["first_name"] or not r["last_name"]:
            problems.append("first and last name are required")
        if r["gender"].upper() not in {"M", "F"}:
            problems.append("gender must be M or F")
        intake = intakes.get(r["intake_code"].upper())
        if not intake:
            problems.append(f"unknown intake '{r['intake_code']}'")
        company = companies.get(r["company_code"].upper()) if r["company_code"] else None
        if r["company_code"] and not company:
            problems.append(f"unknown company '{r['company_code']}'")
        platoon = None
        if r["platoon_code"]:
            platoon = platoons.get((r["company_code"].upper(), r["platoon_code"].upper()))
            if not platoon:
                problems.append(f"platoon '{r['platoon_code']}' not found in company '{r['company_code']}'")
        try:
            adm = date.fromisoformat(r["admission_date"])
        except ValueError:
            adm = None
            problems.append("admission_date must be YYYY-MM-DD")
        status = (r["status"] or "ACTIVE").upper()
        if status not in statuses:
            problems.append(f"invalid status '{r['status']}'")
        if problems:
            errors.append(f"Row {n}: " + "; ".join(problems))
            continue
        rows.append(Cadet(cadet_number=num, first_name=r["first_name"][:80], last_name=r["last_name"][:80],
                          gender=r["gender"].upper(), intake=intake, company=company, platoon=platoon,
                          admission_date=adm, status=status, created_by=request.user, updated_by=request.user))
    if errors:
        log_event("cadet.import_rejected", request=request, outcome="FAILURE", metadata={"errors": len(errors)})
        return 0, errors[:50]
    with transaction.atomic():
        for cadet in rows:
            cadet.full_clean()
            cadet.save()
            CadetAssignmentHistory.objects.create(cadet=cadet, to_intake=cadet.intake, to_company=cadet.company,
                                                  to_platoon=cadet.platoon, reason="CSV import",
                                                  changed_by=request.user)
    from discipline.grading import recalculate

    for cadet in rows:
        recalculate(cadet, actor=request.user, trigger="registration")
    log_event("cadet.imported", request=request, metadata={"created": len(rows)})
    return len(rows), []
