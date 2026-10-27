from django.conf import settings
from django.db import models


class ApplicationSetting(models.Model):
    """Typed key/value settings editable by administrators."""

    class ValueType(models.TextChoices):
        BOOL = "bool", "Yes/No"
        INT = "int", "Number"
        TEXT = "text", "Text"

    key = models.CharField(max_length=60, unique=True)
    label = models.CharField(max_length=120)
    value = models.CharField(max_length=255)
    value_type = models.CharField(max_length=4, choices=ValueType.choices)
    description = models.CharField(max_length=255, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key

    @property
    def typed_value(self):
        if self.value_type == self.ValueType.BOOL:
            return self.value.lower() in {"1", "true", "yes", "on"}
        if self.value_type == self.ValueType.INT:
            return int(self.value)
        return self.value


DEFAULT_SETTINGS = {
    "require_company_review": ("Require company-level review", "true", "bool",
                               "If off, platoon approval is final."),
    "review_overdue_days": ("Review overdue after (days)", "3", "int",
                            "Pending reviews older than this are flagged as overdue."),
    "email_notifications": ("Send e-mail notifications", "false", "bool",
                            "E-mails never contain incident or medical details."),
    "institution_name": ("Institution name", "Officer Cadet Training Academy", "text", "Shown in the header."),
}


def get_setting(key: str):
    try:
        return ApplicationSetting.objects.get(key=key).typed_value
    except ApplicationSetting.DoesNotExist:
        label, value, vtype, _ = DEFAULT_SETTINGS[key]
        return ApplicationSetting(key=key, value=value, value_type=vtype).typed_value


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField(max_length=3000)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
