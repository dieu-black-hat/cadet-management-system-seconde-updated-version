from django import forms
from django.utils import timezone

from accounts.forms import StyledFormMixin
from core.files import ALLOWED_IMAGES, validate_upload

from .models import Cadet, Company, Intake, Platoon


class PlatoonSelect(forms.Select):
    """Adds data-company to each option so the browser can filter platoons by company."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-company"] = str(instance.company_id)
        return option


class CadetForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Cadet
        fields = ["cadet_number", "first_name", "last_name", "gender", "admission_date", "status",
                  "intake", "company", "platoon", "photo", "notes"]
        widgets = {
            "admission_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3, "col": "col-12"}),
            "platoon": PlatoonSelect(),
            "photo": forms.FileInput(attrs={"accept": "image/png,image/jpeg"}),
        }
        help_texts = {"cadet_number": "Unique registration number, e.g. OC-2026-014.",
                      "notes": "Administrative notes only. Do not record medical or disciplinary details here."}

    def __init__(self, *args, can_assign=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["intake"].queryset = Intake.objects.filter(is_active=True) | Intake.objects.filter(
            pk=getattr(self.instance, "intake_id", None))
        self.fields["company"].queryset = Company.objects.filter(is_active=True)
        self.fields["platoon"].queryset = Platoon.objects.filter(is_active=True).select_related("company")
        self.fields["company"].widget.attrs["data-company-select"] = self["platoon"].auto_id
        if not can_assign:
            for f in ("intake", "company", "platoon"):
                self.fields[f].disabled = True
        if self.instance.pk:
            # Organisational moves go through the dedicated "Reassign" action so history is captured.
            for f in ("intake", "company", "platoon"):
                self.fields[f].disabled = True
                self.fields[f].help_text = "Use “Reassign” to move this cadet; the change is recorded."

    def clean_cadet_number(self):
        value = self.cleaned_data["cadet_number"].strip().upper()
        if Cadet.objects.filter(cadet_number=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A cadet with this number is already registered.")
        return value

    def clean_admission_date(self):
        d = self.cleaned_data["admission_date"]
        if d and d > timezone.localdate():
            raise forms.ValidationError("Admission date cannot be in the future.")
        return d

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "content_type"):  # newly uploaded
            validate_upload(photo, allowed=ALLOWED_IMAGES, max_mb=2)
        return photo


class ReassignForm(StyledFormMixin, forms.Form):
    intake = forms.ModelChoiceField(queryset=Intake.objects.all())
    company = forms.ModelChoiceField(queryset=Company.objects.filter(is_active=True), required=False)
    platoon = forms.ModelChoiceField(queryset=Platoon.objects.filter(is_active=True).select_related("company"),
                                     required=False, widget=PlatoonSelect())
    reason = forms.CharField(max_length=255, min_length=5, widget=forms.TextInput(attrs={"col": "col-12"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].widget.attrs["data-company-select"] = self["platoon"].auto_id

    def clean(self):
        data = super().clean()
        company, platoon = data.get("company"), data.get("platoon")
        if platoon and not company:
            self.add_error("company", "Select the company that contains this platoon.")
        if platoon and company and platoon.company_id != company.pk:
            self.add_error("platoon", "This platoon belongs to a different company.")
        return data


class CadetFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=80)
    intake = forms.ModelChoiceField(queryset=Intake.objects.all(), required=False, empty_label="All intakes")
    company = forms.ModelChoiceField(queryset=Company.objects.all(), required=False, empty_label="All companies")
    platoon = forms.ModelChoiceField(queryset=Platoon.objects.select_related("company"), required=False,
                                     empty_label="All platoons")
    status = forms.ChoiceField(required=False, choices=[("", "Any status")] + list(Cadet.Status.choices))
    sort = forms.ChoiceField(required=False, choices=[("name", "Name"), ("number", "Cadet number"),
                                                      ("-admission", "Newest admission"), ("score", "Lowest score")])


class ImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(help_text="CSV, max 1 MB, UTF-8. Columns: cadet_number, first_name, last_name, gender (M/F), "
                                     "intake_code, company_code, platoon_code, admission_date (YYYY-MM-DD), status.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file.")
        if f.size > 1024 * 1024:
            raise forms.ValidationError("The file is larger than 1 MB.")
        return f


class IntakeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Intake
        fields = ["code", "name", "start_date", "end_date", "is_active"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}),
                   "end_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        data = super().clean()
        if data.get("end_date") and data.get("start_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "End date must be after the start date.")
        return data


class CompanyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Company
        fields = ["code", "name", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2, "col": "col-12"})}


class PlatoonForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Platoon
        fields = ["company", "code", "name", "is_active"]
