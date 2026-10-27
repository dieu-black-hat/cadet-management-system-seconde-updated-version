from django import forms
from django.utils import timezone

from accounts.forms import StyledFormMixin
from core.files import validate_upload
from discipline.forms import CadetChoiceField

from .models import MedicalRecord


class MedicalRecordForm(StyledFormMixin, forms.ModelForm):
    cadet = CadetChoiceField(queryset=None)

    class Meta:
        model = MedicalRecord
        fields = ["cadet", "record_type", "title", "assessment_date", "fitness_status", "status", "follow_up_date",
                  "clinical_notes", "command_summary"]
        widgets = {
            "assessment_date": forms.DateInput(attrs={"type": "date"}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
            "clinical_notes": forms.Textarea(attrs={"rows": 6, "col": "col-12"}),
            "command_summary": forms.TextInput(attrs={"col": "col-12"}),
        }
        help_texts = {"clinical_notes": "Visible to authorised medical personnel only. Use fictional data in demos."}

    def __init__(self, *args, cadet_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cadet"].queryset = cadet_queryset
        if self.instance.pk:
            self.fields["cadet"].disabled = True

    def clean_assessment_date(self):
        d = self.cleaned_data["assessment_date"]
        if d > timezone.localdate():
            raise forms.ValidationError("Assessment date cannot be in the future.")
        return d

    def clean(self):
        data = super().clean()
        if data.get("status") == MedicalRecord.Status.FOLLOW_UP and not data.get("follow_up_date"):
            self.add_error("follow_up_date", "Set a follow-up date when follow-up is required.")
        if data.get("follow_up_date") and data.get("assessment_date") and data["follow_up_date"] < data["assessment_date"]:
            self.add_error("follow_up_date", "Follow-up must be after the assessment date.")
        return data


class MedicalAttachmentForm(StyledFormMixin, forms.Form):
    file = forms.FileField(help_text="PDF, JPG, PNG or DOCX, up to 5 MB. Stored privately.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        self.validated = validate_upload(f)
        return f


class MedicalFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=80)
    status = forms.ChoiceField(required=False, choices=[("", "Any status")] + list(MedicalRecord.Status.choices))
    fitness = forms.ChoiceField(required=False, choices=[("", "Any fitness")] + list(MedicalRecord.Fitness.choices))
    record_type = forms.ChoiceField(required=False, choices=[("", "Any type")] + list(MedicalRecord.RecordType.choices))
