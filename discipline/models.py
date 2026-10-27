import uuid
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from cadets.models import Cadet, Company, Platoon


class Severity(models.TextChoices):
    MINOR = "MINOR", "Minor"
    MODERATE = "MODERATE", "Moderate"
    MAJOR = "MAJOR", "Major"
    SEVERE = "SEVERE", "Severe"


class IncidentCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "incident categories"

    def __str__(self):
        return self.name


class DisciplinaryStatement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Pending platoon review"
        COMPANY_REVIEW = "COMPANY_REVIEW", "Pending company review"
        APPROVED = "APPROVED", "Approved (final)"
        REJECTED = "REJECTED", "Rejected"
        RETURNED = "RETURNED", "Returned for correction"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    reference = models.CharField(max_length=24, unique=True, editable=False)
    cadet = models.ForeignKey(Cadet, on_delete=models.PROTECT, related_name="statements")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="statements")
    category = models.ForeignKey(IncidentCategory, on_delete=models.PROTECT, related_name="statements")
    severity = models.CharField(max_length=10, choices=Severity.choices)
    title = models.CharField(max_length=150)
    incident_at = models.DateTimeField("incident date & time")
    location = models.CharField(max_length=120, blank=True)
    description = models.TextField("factual description")
    observations = models.TextField("behavioural observations", blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)

    # Routing snapshot taken at submission (the units responsible for review)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="statements")
    platoon = models.ForeignKey(Platoon, null=True, blank=True, on_delete=models.PROTECT, related_name="statements")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    last_transition_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)  # optimistic concurrency token
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "platoon"]),
            models.Index(fields=["status", "company"]),
            models.Index(fields=["cadet", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} – {self.title}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"DS-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_editable(self):
        return self.status in {self.Status.DRAFT, self.Status.RETURNED}

    @property
    def is_pending(self):
        return self.status in {self.Status.SUBMITTED, self.Status.COMPANY_REVIEW}

    @property
    def next_action_label(self):
        return {
            self.Status.DRAFT: "Author to submit",
            self.Status.SUBMITTED: "Platoon commander to review",
            self.Status.COMPANY_REVIEW: "Company commander to decide",
            self.Status.RETURNED: "Author to correct & resubmit",
        }.get(self.status, "No further action")


class WorkflowTransition(models.Model):
    """Immutable decision history for a statement."""

    statement = models.ForeignKey(DisciplinaryStatement, on_delete=models.CASCADE, related_name="transitions")
    action = models.CharField(max_length=30)
    from_status = models.CharField(max_length=16, choices=DisciplinaryStatement.Status.choices)
    to_status = models.CharField(max_length=16, choices=DisciplinaryStatement.Status.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    actor_role = models.CharField(max_length=20)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class StatementReview(models.Model):
    """Reviewer comments recorded without changing state (e.g. notes for the file)."""

    statement = models.ForeignKey(DisciplinaryStatement, on_delete=models.CASCADE, related_name="reviews")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


def statement_attachment_path(instance, filename):
    return f"statement_attachments/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class StatementAttachment(models.Model):
    statement = models.ForeignKey(DisciplinaryStatement, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=statement_attachment_path)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]


# ---------------------------------------------------------------------------
# Configurable, versioned grading policy
# ---------------------------------------------------------------------------
hex_color = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use a hex colour such as #1F7A3D.")


class DisciplinePolicy(models.Model):
    """
    A grading policy version. Once a version has been activated it becomes
    read-only; changes are made by creating a new version so that historical
    assessments stay explainable.
    """

    name = models.CharField(max_length=120)
    version = models.PositiveIntegerField(unique=True)
    description = models.TextField(blank=True)
    base_score = models.PositiveIntegerField(default=100, validators=[MinValueValidator(10), MaxValueValidator(1000)])
    period_days = models.PositiveIntegerField(
        default=0, help_text="Only count approved statements whose incident is within this many days (0 = all time)."
    )
    is_active = models.BooleanField(default=False)
    was_activated = models.BooleanField(default=False, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        verbose_name_plural = "discipline policies"
        constraints = [
            models.UniqueConstraint(fields=["is_active"], condition=Q(is_active=True), name="single_active_policy")
        ]

    def __str__(self):
        return f"v{self.version} – {self.name}"

    @property
    def is_locked(self):
        return self.was_activated


class SeverityWeight(models.Model):
    policy = models.ForeignKey(DisciplinePolicy, on_delete=models.CASCADE, related_name="severity_weights")
    severity = models.CharField(max_length=10, choices=Severity.choices)
    points = models.PositiveIntegerField(validators=[MaxValueValidator(1000)])

    class Meta:
        ordering = ["points"]
        constraints = [models.UniqueConstraint(fields=["policy", "severity"], name="unique_severity_per_policy")]


class GradeBand(models.Model):
    policy = models.ForeignKey(DisciplinePolicy, on_delete=models.CASCADE, related_name="bands")
    label = models.CharField(max_length=50)
    color = models.CharField(max_length=7, validators=[hex_color])
    icon = models.CharField(max_length=40, default="bi-circle-fill", help_text="Bootstrap icon class")
    min_score = models.IntegerField()
    max_score = models.IntegerField()
    description = models.CharField(max_length=255, blank=True)
    requires_review = models.BooleanField(
        default=False, help_text="Flag cadets in this band for human review (never automatic dismissal)."
    )

    class Meta:
        ordering = ["-max_score"]
        constraints = [
            models.CheckConstraint(condition=Q(max_score__gte=models.F("min_score")), name="band_max_gte_min"),
            models.UniqueConstraint(fields=["policy", "label"], name="unique_band_label_per_policy"),
        ]

    def __str__(self):
        return f"{self.label} ({self.min_score}–{self.max_score})"


class DisciplineAssessment(models.Model):
    """Snapshot of a cadet's grade under a specific policy version."""

    cadet = models.ForeignKey(Cadet, on_delete=models.CASCADE, related_name="assessments")
    policy = models.ForeignKey(DisciplinePolicy, on_delete=models.PROTECT, related_name="assessments")
    score = models.IntegerField()
    calculated_score = models.IntegerField()
    band_label = models.CharField(max_length=50)
    band_color = models.CharField(max_length=7)
    band_icon = models.CharField(max_length=40, default="bi-circle-fill")
    requires_review = models.BooleanField(default=False)
    approved_statement_count = models.PositiveIntegerField(default=0)
    explanation = models.JSONField(default=dict)
    is_current = models.BooleanField(default=True, db_index=True)
    is_override = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=255, blank=True)
    trigger = models.CharField(max_length=40, default="recalculation")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["cadet"], condition=Q(is_current=True), name="single_current_assessment")
        ]
