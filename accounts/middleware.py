from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class AccountStatusMiddleware:
    """Immediately ends the session of a user who has been suspended or deactivated."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.can_sign_in:
            logout(request)
            messages.error(request, "Your account is not active. Contact the system administrator.")
            return redirect("accounts:login")
        return self.get_response(request)
