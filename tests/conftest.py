"""Shared fixtures: a small synthetic organisation with one user per role."""
from datetime import date, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from accounts.models import User
from cadets.models import Cadet, Company, Intake, Platoon, StaffAssignment
from core.permissions import Role
from discipline.models import DisciplinePolicy, GradeBand, IncidentCategory, SeverityWeight

PASSWORD = "Test-Passw0rd!x"


@pytest.fixture
def org(db):
    admin = User.objects.create_superuser("admin@test.local", PASSWORD, first_name="Ad", last_name="Min")
    intake = Intake.objects.create(code="INT-T", name="Test intake", start_date=date(2026, 1, 1))
    a = Company.objects.create(code="ACOY", name="Alpha")
    b = Company.objects.create(code="BCOY", name="Bravo")
    a1 = Platoon.objects.create(company=a, code="P1", name="Platoon 1")
    a2 = Platoon.objects.create(company=a, code="P2", name="Platoon 2")
    b1 = Platoon.objects.create(company=b, code="P1", name="Platoon 1")

    def mk(email, role, **unit):
        u = User.objects.create_user(email, PASSWORD, first_name=email.split("@")[0], last_name="T", role=role)
        if unit:
            StaffAssignment.objects.create(user=u, assigned_by=admin, **unit)
        return u

    users = {
        "admin": admin,
        "instructor": mk("ins@test.local", Role.INSTRUCTOR, company=a),
        "instructor_b": mk("insb@test.local", Role.INSTRUCTOR, company=b),
        "pc_a1": mk("pca1@test.local", Role.PLATOON_COMMANDER, platoon=a1),
        "pc_a2": mk("pca2@test.local", Role.PLATOON_COMMANDER, platoon=a2),
        "pc_b1": mk("pcb1@test.local", Role.PLATOON_COMMANDER, platoon=b1),
        "cc_a": mk("cca@test.local", Role.COMPANY_COMMANDER, company=a),
        "cc_b": mk("ccb@test.local", Role.COMPANY_COMMANDER, company=b),
        "doctor": mk("doc@test.local", Role.DOCTOR, company=a),
        "auditor": mk("aud@test.local", Role.AUDITOR),
    }

    def cadet(num, company, platoon):
        return Cadet.objects.create(cadet_number=num, first_name="Cad", last_name=num, gender="M", intake=intake,
                                    company=company, platoon=platoon, admission_date=date(2026, 1, 5),
                                    created_by=admin)

    cadets = {"a1": cadet("OC-A1-001", a, a1), "a2": cadet("OC-A2-001", a, a2), "b1": cadet("OC-B1-001", b, b1)}

    policy = DisciplinePolicy.objects.create(name="Test policy", version=1, created_by=admin)
    for sev, pts in [("MINOR", 5), ("MODERATE", 10), ("MAJOR", 20), ("SEVERE", 35)]:
        SeverityWeight.objects.create(policy=policy, severity=sev, points=pts)
    for label, lo, hi, review in [("High", 90, 100, False), ("Good", 75, 89, False), ("Moderate", 50, 74, False),
                                  ("Poor", 0, 49, True)]:
        GradeBand.objects.create(policy=policy, label=label, color="#123456", min_score=lo, max_score=hi,
                                 requires_review=review)
    policy.is_active = policy.was_activated = True
    policy.save()
    category = IncidentCategory.objects.create(name="Punctuality")
    return {"users": users, "cadets": cadets, "companies": {"a": a, "b": b},
            "platoons": {"a1": a1, "a2": a2, "b1": b1}, "intake": intake, "policy": policy, "category": category}


@pytest.fixture
def login():
    def _login(user):
        c = Client()
        assert c.login(username=user.email, password=PASSWORD)
        return c
    return _login


@pytest.fixture
def make_statement(org):
    from discipline.models import DisciplinaryStatement

    def _make(cadet_key="a1", author="instructor", severity="MINOR"):
        return DisciplinaryStatement.objects.create(
            cadet=org["cadets"][cadet_key], submitted_by=org["users"][author], category=org["category"],
            severity=severity, title="Late for parade", incident_at=timezone.now() - timedelta(days=1),
            description="The cadet arrived twelve minutes late for the 06:00 parade.")
    return _make
