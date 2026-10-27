from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from accounts.forms import StyledFormMixin
from core.files import validate_upload

from .models import (DisciplinaryStatement, DisciplinePolicy, GradeBand, IncidentCategory, Severity,
                     SeverityWeight)


class CadetChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.cadet_number} — {obj.full_name} ({obj.company.code if obj.company else 'no company'}"\
               f"{' / ' + obj.platoon.name if obj.platoon else ''})"


class StatementForm(StyledFormMixin, forms.ModelForm):
    cadet = CadetChoiceField(queryset=None)

    class Meta:
        model = DisciplinaryStatement
        fields = ["cadet", "title", "category", "severity", "incident_at", "location", "description", "observations"]
        widgets = {
            "incident_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "description": forms.Textarea(attrs={"rows": 5, "col": "col-12"}),
            "observations": forms.Textarea(attrs={"rows": 3, "col": "col-12"}),
        }
        help_texts = {
            "description": "State facts: what happened, when and where. Avoid opinions. Minimum 20 characters.",
            "observations": "Optional: relevant behaviour observed before or after the incident.",
        }

    def __init__(self, *args, cadet_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cadet"].queryset = cadet_queryset
        self.fields["category"].queryset = IncidentCategory.objects.filter(is_active=True)
        self.fields["incident_at"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean_incident_at(self):
        value = self.cleaned_data["incident_at"]
        if value > timezone.now():
            raise forms.ValidationError("The incident cannot be in the future.")
        if value < timezone.now() - timezone.timedelta(days=365):
            raise forms.ValidationError("Incidents older than one year must be recorded by an administrator.")
        return value

    def clean_description(self):
        text = self.cleaned_data["description"].strip()
        if len(text) < 20:
            raise forms.ValidationError("Write at least 20 characters describing the facts.")
        return text


class AttachmentForm(StyledFormMixin, forms.Form):
    file = forms.FileField(help_text="PDF, JPG, PNG or DOCX, up to 5 MB.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        self.validated = validate_upload(f)
        return f


class DecisionForm(forms.Form):
    action = forms.CharField(max_length=30)
    comment = forms.CharField(required=False, max_length=2000)
    version = forms.IntegerField(min_value=1)


class CommentForm(StyledFormMixin, forms.Form):
    comment = forms.CharField(max_length=2000, min_length=3, widget=forms.Textarea(attrs={"rows": 2}))


class StatementFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=80)
    status = forms.ChoiceField(required=False, choices=[("", "Any status")] + list(DisciplinaryStatement.Status.choices))
    category = forms.ModelChoiceField(queryset=IncidentCategory.objects.all(), required=False,
                                      empty_label="All categories")
    severity = forms.ChoiceField(required=False, choices=[("", "Any severity")] + list(Severity.choices))
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        d = super().clean()
        if d.get("date_from") and d.get("date_to") and d["date_from"] > d["date_to"]:
            raise forms.ValidationError("'From' date must be before 'to' date.")
        return d


class PolicyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DisciplinePolicy
        fields = ["name", "description", "base_score", "period_days"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2, "col": "col-12"})}


class BandForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GradeBand
        fields = ["label", "color", "icon", "min_score", "max_score", "requires_review", "description"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class WeightForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SeverityWeight
        fields = ["severity", "points"]


BandFormSet = inlineformset_factory(DisciplinePolicy, GradeBand, form=BandForm, extra=1, can_delete=True,
                                    min_num=1, validate_min=True)
WeightFormSet = inlineformset_factory(DisciplinePolicy, SeverityWeight, form=WeightForm, extra=0, can_delete=False,
                                      min_num=len(Severity.choices), max_num=len(Severity.choices))
