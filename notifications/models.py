from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Kind(models.TextChoices):
        STATEMENT_SUBMITTED = "STATEMENT_SUBMITTED", "Statement submitted"
        STATEMENT_FORWARDED = "STATEMENT_FORWARDED", "Statement forwarded for review"
        STATEMENT_APPROVED = "STATEMENT_APPROVED", "Statement approved"
        STATEMENT_REJECTED = "STATEMENT_REJECTED", "Statement rejected"
        STATEMENT_RETURNED = "STATEMENT_RETURNED", "Statement returned for correction"
        STATEMENT_RESUBMITTED = "STATEMENT_RESUBMITTED", "Statement resubmitted"
        REVIEW_OVERDUE = "REVIEW_OVERDUE", "Review overdue"
        ACCOUNT = "ACCOUNT", "Account change"
        ASSESSMENT = "ASSESSMENT", "Assessment requires review"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=300, blank=True)
    link = models.CharField(max_length=200, blank=True)
    dedupe_key = models.CharField(max_length=120, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"], condition=~models.Q(dedupe_key=""),
                name="unique_notification_dedupe",
            )
        ]

    def __str__(self):
        return self.title
