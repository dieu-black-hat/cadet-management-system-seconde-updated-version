"""
Notification service. In-app notifications are always created; e-mail is sent
only when the `email_notifications` setting is enabled, and e-mails never
contain incident narrative or medical information — just a link that performs
a fresh authorization check.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction

from core.models import get_setting

from .models import Notification

logger = logging.getLogger(__name__)


def notify(recipients, kind, title, message="", link="", dedupe_key=""):
    created = []
    seen = set()
    for user in recipients:
        if user is None or user.pk in seen or not user.can_sign_in:
            continue
        seen.add(user.pk)
        try:
            with transaction.atomic():
                created.append(Notification.objects.create(
                    recipient=user, kind=kind, title=title[:150], message=message[:300], link=link,
                    dedupe_key=dedupe_key,
                ))
        except IntegrityError:
            # Idempotency: the same dedupe_key was already delivered to this user.
            continue
    if created and get_setting("email_notifications"):
        transaction.on_commit(lambda: _send_emails(created))
    return created


def _send_emails(notifications):
    for n in notifications:
        try:
            send_mail(
                subject=f"[OCMS] {n.get_kind_display()}",
                message=(
                    f"Hello {n.recipient.get_full_name()},\n\n"
                    f"There is an update waiting for you in the Officer Cadet Management System.\n"
                    f"Sign in to view it: {n.link}\n\n"
                    "This e-mail intentionally contains no record details."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[n.recipient.email],
                fail_silently=False,
            )
        except Exception:  # pragma: no cover - mail server failures must not break workflows
            logger.exception("Failed to send notification e-mail id=%s", n.pk)
