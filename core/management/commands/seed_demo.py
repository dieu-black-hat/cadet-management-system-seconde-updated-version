"""
Load clearly-synthetic demonstration data.

    python manage.py seed_demo            # default demo password, DEBUG only
    python manage.py seed_demo --reset    # wipe demo data first (DEBUG only)

Refuses to run when DEBUG is False: production must never be seeded with
default privileged credentials.
"""
import random
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from cadets.models import Cadet, CadetAssignmentHistory, Company, Intake, Platoon, StaffAssignment
from core.permissions import Role
from discipline import grading, workflow
from discipline.models import (DisciplinaryStatement, DisciplinePolicy, GradeBand, IncidentCategory,
                               SeverityWeight)
from medical.models import MedicalRecord

FIRST_M = ["Eric", "Jean", "Patrick", "Olivier", "David", "Emmanuel", "Fabrice", "Claude", "Innocent", "Kevin",
           "Samuel", "Gilbert", "Yves", "Didier", "Thierry", "Pacifique", "Moses", "Alain", "Bosco", "Cedric"]
FIRST_F = ["Aline", "Diane", "Grace", "Josiane", "Clarisse", "Sandrine", "Ange", "Esther", "Nadine", "Divine",
           "Alice", "Belyse", "Chantal", "Ornella", "Gisele"]
LAST = ["Mugisha", "Niyonzima", "Uwase", "Habimana", "Ishimwe", "Nshimiyimana", "Mutoni", "Hakizimana", "Kamanzi",
        "Byiringiro", "Iradukunda", "Ndayisaba", "Umutoni", "Gakoko", "Bizimana", "Uwimana", "Rukundo", "Mukamana",
        "Twagirayezu", "Nkurunziza", "Ingabire", "Munyaneza", "Tuyisenge", "Kayitesi", "Mugabo"]

CATEGORIES = [
    ("Punctuality", "Late for parade, class or duty."),
    ("Dress and turnout", "Uniform and personal turnout below standard."),
    ("Barrack inspection", "Room or equipment fails inspection."),
    ("Absence without leave", "Absent from place of duty without authorisation."),
    ("Insubordination", "Failure to obey a lawful order or disrespect to a superior."),
    ("Weapon handling", "Unsafe handling or care of weapons and equipment."),
    ("Academic integrity", "Misconduct in assessments or coursework."),
    ("Conduct unbecoming", "Behaviour that discredits the cadet or the academy."),
]

INCIDENTS = {
    "Punctuality": [("Late for morning parade", "MINOR"), ("Late return from weekend pass", "MODERATE")],
    "Dress and turnout": [("Boots not polished at inspection", "MINOR"), ("Incomplete uniform on guard duty", "MODERATE")],
    "Barrack inspection": [("Bed space not prepared for inspection", "MINOR"), ("Locker left unsecured", "MINOR")],
    "Absence without leave": [("Absent from evening roll call", "MAJOR"), ("Left barracks without permission", "SEVERE")],
    "Insubordination": [("Refused instruction from section leader", "MAJOR"), ("Argued with duty officer", "MODERATE")],
    "Weapon handling": [("Muzzle discipline breach on range", "MAJOR"), ("Weapon not cleaned after exercise", "MODERATE")],
    "Academic integrity": [("Unauthorised notes during map-reading test", "MAJOR")],
    "Conduct unbecoming": [("Disrespectful language in mess hall", "MODERATE")],
}


class Command(BaseCommand):
    help = "Seed synthetic demonstration data (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Cadet@Demo2026!",
                            help="Password for all demo accounts (development only).")
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data first.")
        parser.add_argument("--cadets-per-platoon", type=int, default=8)

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=True. Never seed production with demo credentials.")
        if Cadet.objects.exists() and not opts["reset"]:
            raise CommandError("Data already exists. Re-run with --reset to start from a clean demo dataset.")
        rnd = random.Random(2026)
        if opts["reset"]:
            self._reset()
        with transaction.atomic():
            self._seed(rnd, opts["password"], opts["cadets_per_platoon"])
        self._print_accounts(opts["password"])

    # ------------------------------------------------------------------
    def _reset(self):
        from django.db import connection

        tables = ["notifications_notification", "discipline_disciplineassessment", "discipline_workflowtransition",
                  "discipline_statementreview", "discipline_statementattachment", "discipline_disciplinarystatement",
                  "discipline_gradeband", "discipline_severityweight", "discipline_disciplinepolicy",
                  "discipline_incidentcategory", "medical_medicalattachment", "medical_medicalrecordrevision",
                  "medical_medicalrecord", "cadets_cadetassignmenthistory", "cadets_cadet",
                  "cadets_staffassignment", "cadets_platoon", "cadets_company", "cadets_intake",
                  "accounts_permissiongrant", "accounts_loginattempt", "audit_auditevent", "core_contactmessage",
                  "django_session", "accounts_user_groups", "accounts_user_user_permissions", "accounts_user"]
        with connection.cursor() as cur:
            # TRUNCATE is used deliberately: the audit table blocks row-level DELETE.
            cur.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
        self.stdout.write(self.style.WARNING("Existing data removed."))

    def _user(self, email, first, last, role, rank, pw, sn):
        u = User.objects.create_user(email=email, password=pw, first_name=first, last_name=last, role=role,
                                     rank=rank, service_number=sn, phone="+250 7" + sn[-8:])
        return u

    def _seed(self, rnd, pw, per_platoon):
        now = timezone.now()
        admin = User.objects.create_superuser(email="admin@ocms.local", password=pw, first_name="Ange",
                                              last_name="Uwamahoro", rank="Maj", service_number="SVC-10000001")
        intakes = [
            Intake.objects.create(code="INT-2025", name="Intake 2025 (Senior)", start_date=date(2025, 1, 13)),
            Intake.objects.create(code="INT-2026", name="Intake 2026 (Junior)", start_date=date(2026, 1, 12)),
        ]
        companies = []
        for code, name in [("ACOY", "Alpha Company"), ("BCOY", "Bravo Company"), ("CCOY", "Charlie Company")]:
            c = Company.objects.create(code=code, name=name, description=f"{name} — synthetic demo unit")
            companies.append(c)
            for i in (1, 2, 3):
                Platoon.objects.create(company=c, code=f"P{i}", name=f"Platoon {i}")

        sn = iter(range(10000002, 10009999))
        ranks_cc, ranks_pc = ["Capt", "Capt", "Maj"], ["Lt", "2Lt", "Lt"]
        staff = {"company": {}, "platoon": {}, "instructor": {}}
        names = iter([(f, l) for f, l in zip(FIRST_M + FIRST_F, reversed(LAST * 2))])
        for idx, c in enumerate(companies):
            f, l = next(names)
            cc = self._user(f"cc.{c.code.lower()}@ocms.local", f, l, Role.COMPANY_COMMANDER, ranks_cc[idx], pw,
                            f"SVC-{next(sn)}")
            StaffAssignment.objects.create(user=cc, company=c, assigned_by=admin)
            staff["company"][c.pk] = cc
            f, l = next(names)
            ins = self._user(f"instructor.{c.code.lower()}@ocms.local", f, l, Role.INSTRUCTOR, "Sgt", pw,
                             f"SVC-{next(sn)}")
            StaffAssignment.objects.create(user=ins, company=c, assigned_by=admin)
            staff["instructor"][c.pk] = ins
            for p in c.platoons.all():
                f, l = next(names)
                pc = self._user(f"pc.{c.code.lower()}.{p.code.lower()}@ocms.local", f, l, Role.PLATOON_COMMANDER,
                                rnd.choice(ranks_pc), pw, f"SVC-{next(sn)}")
                StaffAssignment.objects.create(user=pc, platoon=p, assigned_by=admin)
                staff["platoon"][p.pk] = pc
        doctor = self._user("doctor@ocms.local", "Diane", "Mukeshimana", Role.DOCTOR, "Capt (Dr)", pw, f"SVC-{next(sn)}")
        for c in companies:
            StaffAssignment.objects.create(user=doctor, company=c, assigned_by=admin)
        self._user("auditor@ocms.local", "Pacifique", "Ndayambaje", Role.AUDITOR, "Mr", pw, f"SVC-{next(sn)}")

        # Grading policy v1 (configurable; edit or replace it in the app)
        policy = DisciplinePolicy.objects.create(
            name="Academy discipline standard", version=1, base_score=100, period_days=0, created_by=admin,
            description="Every cadet starts at 100; each approved statement deducts points by severity.")
        for sev, pts in [("MINOR", 5), ("MODERATE", 10), ("MAJOR", 20), ("SEVERE", 35)]:
            SeverityWeight.objects.create(policy=policy, severity=sev, points=pts)
        for label, color, icon, lo, hi, review, desc in [
            ("High discipline", "#1F7A3D", "bi-star-fill", 90, 100, False, "Exemplary conduct and adherence to standards."),
            ("Good discipline", "#1D5FA8", "bi-check-circle-fill", 75, 89, False, "Commendable conduct with minor lapses."),
            ("Moderate discipline", "#A76A00", "bi-exclamation-circle-fill", 50, 74, False,
             "Meets minimum standards; mentoring advised."),
            ("Poor discipline", "#B3261E", "bi-x-octagon-fill", 0, 49, True,
             "Below standard — flagged for command review (not an automatic sanction)."),
        ]:
            GradeBand.objects.create(policy=policy, label=label, color=color, icon=icon, min_score=lo, max_score=hi,
                                     requires_review=review, description=desc)
        policy.is_active = policy.was_activated = True
        policy.activated_at = now
        policy.save()

        cats = {name: IncidentCategory.objects.create(name=name, description=d) for name, d in CATEGORIES}

        # Cadets
        cadets, n = [], 1
        for c in companies:
            for p in c.platoons.all():
                for k in range(per_platoon):
                    female = rnd.random() < 0.3
                    intake = intakes[k % 2]
                    cadet = Cadet.objects.create(
                        cadet_number=f"OC-{intake.code[-4:]}-{n:03d}",
                        first_name=rnd.choice(FIRST_F if female else FIRST_M), last_name=rnd.choice(LAST),
                        gender="F" if female else "M", intake=intake, company=c, platoon=p,
                        admission_date=intake.start_date, created_by=admin, updated_by=admin,
                        status=Cadet.Status.ACTIVE if rnd.random() > 0.05 else Cadet.Status.SUSPENDED,
                    )
                    CadetAssignmentHistory.objects.create(cadet=cadet, to_intake=intake, to_company=c, to_platoon=p,
                                                          reason="Initial registration (synthetic data)",
                                                          changed_by=admin)
                    cadets.append(cadet)
                    n += 1

        # Statements driven through the real workflow engine
        plans = (["APPROVED"] * 45 + ["COMPANY_REVIEW"] * 9 + ["SUBMITTED"] * 12 + ["RETURNED"] * 5
                 + ["REJECTED"] * 6 + ["DRAFT"] * 5)
        rnd.shuffle(plans)
        # concentrate incidents on some cadets so all grade bands appear
        weights = [rnd.choice([0, 0, 0, 1, 1, 2, 4, 7]) for _ in cadets]
        for i, target in enumerate(plans):
            cadet = rnd.choices(cadets, weights=[w + 0.2 for w in weights])[0]
            cat_name = rnd.choice(list(INCIDENTS))
            title, severity = rnd.choice(INCIDENTS[cat_name])
            days_ago = rnd.randint(2, 175)
            incident = timezone.make_aware(datetime.combine(now.date() - timedelta(days=days_ago),
                                                            time(rnd.randint(5, 21), rnd.choice([0, 15, 30, 45]))))
            author = staff["instructor"][cadet.company_id]
            st = DisciplinaryStatement.objects.create(
                cadet=cadet, submitted_by=author, category=cats[cat_name], severity=severity, title=title,
                incident_at=incident, location=rnd.choice(["Parade square", "Barrack block 3", "Range 2",
                                                            "Lecture hall B", "Mess hall", "Main gate"]),
                description=(f"[Synthetic record] At {incident:%H:%M} on {incident:%d %b %Y}, Cadet {cadet.last_name} "
                             f"was observed: {title.lower()}. The cadet was informed and the incident recorded."),
                observations="Cadet acknowledged the incident." if rnd.random() > 0.5 else "",
            )
            if target == "DRAFT":
                continue
            pc = staff["platoon"][cadet.platoon_id]
            cc = staff["company"][cadet.company_id]
            workflow.perform(st.pk, "submit", author)
            if target == "SUBMITTED":
                pass
            elif target == "RETURNED":
                workflow.perform(st.pk, "platoon_return", pc, comment="Please add the time the cadet was found and "
                                                                     "the name of the witnessing NCO.")
            elif target == "REJECTED":
                workflow.perform(st.pk, "platoon_reject", pc, comment="Insufficient evidence; the cadet was on "
                                                                     "authorised medical leave at the time.")
            else:
                workflow.perform(st.pk, "platoon_approve", pc, comment="Facts verified with section leader.")
                if target == "APPROVED":
                    workflow.perform(st.pk, "company_approve", cc, comment="Approved.")
            # Back-date timeline fields so dashboards show realistic ages and turnaround times.
            sub = incident + timedelta(hours=rnd.randint(3, 30))
            last = sub + timedelta(hours=rnd.randint(4, 120))
            if target in ("SUBMITTED", "COMPANY_REVIEW"):
                last = now - timedelta(hours=rnd.randint(2, 140))
                sub = min(sub, last)
            DisciplinaryStatement.objects.filter(pk=st.pk).update(
                submitted_at=sub, last_transition_at=last,
                decided_at=last if target in ("APPROVED", "REJECTED") else None)

        # Medical records (fictional)
        notes = ["Ankle sprain sustained during obstacle course. RICE protocol, review in 7 days.",
                 "Seasonal influenza symptoms; 3 days rest prescribed.",
                 "Routine annual examination: no abnormalities found.",
                 "Lower back strain after load-carry march; physiotherapy referral.",
                 "Fitness test cleared; no restrictions."]
        for cadet in rnd.sample(cadets, 26):
            rtype = rnd.choice(list(MedicalRecord.RecordType.values))
            fit = rnd.choice(["FIT", "FIT", "FIT", "LIMITED", "TEMP_UNFIT"])
            status = rnd.choice(["OPEN", "FOLLOW_UP", "CLOSED", "CLOSED"])
            ad = now.date() - timedelta(days=rnd.randint(1, 120))
            MedicalRecord.objects.create(
                cadet=cadet, record_type=rtype, title=MedicalRecord.RecordType(rtype).label, assessment_date=ad,
                clinical_notes="[Fictional] " + rnd.choice(notes), fitness_status=fit, status=status,
                follow_up_date=ad + timedelta(days=rnd.randint(5, 40)) if status == "FOLLOW_UP" else None,
                command_summary={"FIT": "Fit for all training.", "LIMITED": "No load-carrying for two weeks.",
                                 "TEMP_UNFIT": "Excused from physical training until review."}[fit],
                created_by=doctor, updated_by=doctor)

        for cadet in cadets:
            grading.recalculate(cadet, actor=admin, trigger="seed")

    def _print_accounts(self, pw):
        self.stdout.write(self.style.SUCCESS("\nSynthetic demo data loaded."))
        self.stdout.write(f"All demo accounts use the password: {pw}\n")
        for u in User.objects.order_by("role", "email"):
            self.stdout.write(f"  {u.get_role_display():<28} {u.email}")
