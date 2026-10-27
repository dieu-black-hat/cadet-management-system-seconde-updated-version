"""Notify reviewers about overdue reviews. Safe to run repeatedly (idempotent per day).

Schedule it daily, e.g. cron:  0 7 * * *  /path/venv/bin/python manage.py notify_overdue
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import get_setting
from discipline.models import DisciplinaryStatement as S
from discipline.workflow import _reviewers
from core.permissions import Perm
from notifications.models import Notification
from notifications.services import notify


class Command(BaseCommand):
    help = "Send in-app notifications for reviews pending longer than the configured threshold."

    def handle(self, *args, **opts):
        days = get_setting("review_overdue_days")
        cutoff = timezone.now() - timedelta(days=days)
        today = timezone.localdate().isoformat()
        sent = 0
        for st in S.objects.filter(status__in=[S.Status.SUBMITTED, S.Status.COMPANY_REVIEW],
                                   last_transition_at__lt=cutoff):
            if st.status == S.Status.SUBMITTED:
                people = _reviewers(st, Perm.STATEMENTS_REVIEW_PLATOON, "platoon")
            else:
                people = _reviewers(st, Perm.STATEMENTS_REVIEW_COMPANY, "company")
            sent += len(notify(people, Notification.Kind.REVIEW_OVERDUE,
                               f"Review of {st.reference} is overdue (> {days} days)",
                               link=f"/statements/{st.pk}/", dedupe_key=f"overdue-{st.pk}-{today}"))
        self.stdout.write(self.style.SUCCESS(f"{sent} overdue notification(s) sent."))
