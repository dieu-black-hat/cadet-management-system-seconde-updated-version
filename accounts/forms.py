from django import forms
from django.contrib.auth.forms import AuthenticationForm

from cadets.models import Company, Platoon
from core.permissions import ALL_PERMISSIONS, PERMISSION_LABELS, Role

from .models import User


class StyledFormMixin:
    """Adds Bootstrap classes and accessible attributes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")
            if field.help_text:
                w.attrs.setdefault("aria-describedby", f"id_{self.add_prefix(name)}_help")

    def full_clean(self):
        super().full_clean()
        # Mark invalid widgets only after validation has actually run.
        for name in getattr(self, "_errors", None) or {}:
            if name in self.fields:
                w = self.fields[name].widget
                if "is-invalid" not in w.attrs.get("class", ""):
                    w.attrs["class"] = w.attrs.get("class", "") + " is-invalid"
                w.attrs["aria-invalid"] = "true"


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    error_messages = {
        "invalid_login": "The email or password is incorrect, or the account is not active.",
        "inactive": "The email or password is incorrect, or the account is not active.",
    }


class UserCreateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "role", "rank", "service_number", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["service_number"].required = False

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_service_number(self):
        return self.cleaned_data.get("service_number") or None


class UserEditForm(UserCreateForm):
    pass


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["phone"]
        labels = {"phone": "Contact phone"}


class SuspendForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=255, min_length=5, widget=forms.TextInput(attrs={"col": "col-12"}))


class PermissionGrantForm(StyledFormMixin, forms.Form):
    permission = forms.ChoiceField(choices=[(p, PERMISSION_LABELS[p]) for p in ALL_PERMISSIONS])
    reason = forms.CharField(max_length=255, min_length=5)
    expires_at = forms.DateTimeField(required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
                                     help_text="Optional. Leave blank for no expiry.")


class UnitAssignmentForm(StyledFormMixin, forms.Form):
    company = forms.ModelChoiceField(queryset=Company.objects.filter(is_active=True), required=False,
                                     help_text="Assign to a whole company (company commanders, doctors, instructors).")
    platoon = forms.ModelChoiceField(queryset=Platoon.objects.filter(is_active=True).select_related("company"),
                                     required=False, help_text="Or to a single platoon (platoon commanders, instructors).")

    def clean(self):
        data = super().clean()
        if bool(data.get("company")) == bool(data.get("platoon")):
            raise forms.ValidationError("Choose either a company or a platoon (exactly one).")
        return data


class UserFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=80)
    role = forms.ChoiceField(required=False, choices=[("", "All roles")] + list(Role.choices))
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), ("active", "Active"),
                                                        ("inactive", "Deactivated"), ("suspended", "Suspended")])
