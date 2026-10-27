from django.contrib.auth.backends import ModelBackend


class EmailStatusBackend(ModelBackend):
    """Email-based login that also refuses suspended accounts."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        email = (email or username or "").strip().lower()
        return super().authenticate(request, username=email, password=password, **kwargs)

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and not getattr(user, "is_suspended", False)
