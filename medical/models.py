import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

from cadets.models import Cadet


class MedicalRecord(models.Model):
    """
    Confidential medical record. `clinical_notes` and attachments are visible
    only to medical personnel. Commanders see `fitness_status` and the
    explicitly approved `command_summary` — nothing else.
    """

    class RecordType(models.TextChoices):
        ROUTINE = "ROUTINE", "Routine examination"
        INJURY = "INJURY", "Injury"
        ILLNESS = "ILLNESS", "Illness"
        FITNESS = "FITNESS", "Fitness assessment"
        FOLLOW_UP = "FOLLOW_UP", "Follow-up"

    class Fitness(models.TextChoices):
        FIT = "FIT", "Fit for full training"
        LIMITED = "LIMITED", "Fit – limited duties"
        TEMP_UNFIT = "TEMP_UNFIT", "Temporarily unfit"
        PENDING = "PENDING", "Assessment pending"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        FOLLOW_UP = "FOLLOW_UP", "Follow-up required"
        CLOSED = "CLOSED", "Closed"

    reference = models.CharField(max_length=24, unique=True, editable=False)
    cadet = models.ForeignKey(Cadet, on_delete=models.PROTECT, related_name="medical_records")
    record_type = models.CharField(max_length=12, choices=RecordType.choices)
    title = models.CharField(max_length=150)
    assessment_date = models.DateField()
    clinical_notes = models.TextField("clinical notes (restricted)")
    fitness_status = models.CharField(max_length=12, choices=Fitness.choices, default=Fitness.PENDING)
    command_summary = models.CharField(
        "summary approved for command", max_length=255, blank=True,
        help_text="Non-clinical summary visible to commanders. Do not include diagnoses.",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assessment_date", "-id"]
        indexes = [models.Index(fields=["cadet", "assessment_date"])]

    def __str__(self):
        return f"{self.reference} ({self.get_record_type_display()})"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"MR-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)


class MedicalRecordRevision(models.Model):
    """History of permitted updates (stored inside the restricted module)."""

    record = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name="revisions")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_fields = models.JSONField(default=list)
    previous_values = models.JSONField(default=dict)

    class Meta:
        ordering = ["-changed_at"]


def medical_attachment_path(instance, filename):
    return f"medical/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class MedicalAttachment(models.Model):
    record = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=medical_attachment_path)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
