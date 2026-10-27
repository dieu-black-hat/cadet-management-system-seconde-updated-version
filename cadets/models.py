import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


code_validator = RegexValidator(r"^[A-Za-z0-9\-]{1,20}$", "Use letters, digits and hyphens only (max 20).")


class Intake(TimeStamped):
    code = models.CharField(max_length=20, unique=True, validators=[code_validator])
    name = models.CharField(max_length=120)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")),
                name="intake_end_after_start",
            )
        ]

    def __str__(self):
        return f"{self.code} – {self.name}"


class Company(TimeStamped):
    code = models.CharField(max_length=20, unique=True, validators=[code_validator])
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name


class Platoon(TimeStamped):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="platoons")
    code = models.CharField(max_length=20, validators=[code_validator])
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["company__code", "code"]
        constraints = [models.UniqueConstraint(fields=["company", "code"], name="unique_platoon_code_per_company")]

    def __str__(self):
        return f"{self.company.code} / {self.name}"


def cadet_photo_path(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"cadet_photos/{uuid.uuid4().hex}{ext}"


cadet_number_validator = RegexValidator(
    r"^[A-Z0-9][A-Z0-9\-/]{2,29}$", "Cadet number: 3–30 upper-case letters, digits, '-' or '/'."
)


class Cadet(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        SUSPENDED = "SUSPENDED", "Suspended"
        GRADUATED = "GRADUATED", "Graduated"
        TRANSFERRED = "TRANSFERRED", "Transferred"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    cadet_number = models.CharField(max_length=30, unique=True, validators=[cadet_number_validator])
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    photo = models.ImageField(upload_to=cadet_photo_path, blank=True)
    intake = models.ForeignKey(Intake, on_delete=models.PROTECT, related_name="cadets")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="cadets", null=True, blank=True)
    platoon = models.ForeignKey(Platoon, on_delete=models.PROTECT, related_name="cadets", null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    admission_date = models.DateField()
    notes = models.TextField("administrative notes", blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["company", "platoon"]),
        ]
        constraints = [
            # A platoon may only be set together with a company
            models.CheckConstraint(
                condition=Q(platoon__isnull=True) | Q(company__isnull=False), name="cadet_platoon_requires_company"
            )
        ]

    def __str__(self):
        return f"{self.cadet_number} {self.full_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def initials(self):
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()

    def clean(self):
        if self.platoon_id and self.company_id and self.platoon.company_id != self.company_id:
            raise ValidationError({"platoon": "The selected platoon does not belong to the selected company."})
        if self.platoon_id and not self.company_id:
            raise ValidationError({"company": "Select the company that contains this platoon."})


class CadetAssignmentHistory(models.Model):
    cadet = models.ForeignKey(Cadet, on_delete=models.CASCADE, related_name="assignment_history")
    from_intake = models.ForeignKey(Intake, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_intake = models.ForeignKey(Intake, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_platoon = models.ForeignKey(Platoon, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_platoon = models.ForeignKey(Platoon, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name_plural = "cadet assignment history"


class StaffAssignment(models.Model):
    """
    Links a staff member (instructor, commander, doctor) to the organisational
    unit they are authorised for. Exactly one of company / platoon is set.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="unit_assignments")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="staff")
    platoon = models.ForeignKey(Platoon, null=True, blank=True, on_delete=models.PROTECT, related_name="staff")
    is_active = models.BooleanField(default=True, db_index=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(company__isnull=False) & Q(platoon__isnull=True))
                | (Q(company__isnull=True) & Q(platoon__isnull=False)),
                name="staff_assignment_exactly_one_unit",
            ),
            models.UniqueConstraint(
                fields=["user", "company"], condition=Q(is_active=True, company__isnull=False),
                name="unique_active_company_assignment",
            ),
            models.UniqueConstraint(
                fields=["user", "platoon"], condition=Q(is_active=True, platoon__isnull=False),
                name="unique_active_platoon_assignment",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.unit_label}"

    @property
    def unit_label(self):
        return f"Platoon {self.platoon}" if self.platoon_id else f"Company {self.company}"
