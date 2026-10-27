from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST


@login_required
def notification_list(request):
    qs = request.user.notifications.all()
    if request.GET.get("unread") == "1":
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page_obj": page})


@login_required
def notification_open(request, pk):
    n = get_object_or_404(request.user.notifications, pk=pk)
    if not n.is_read:
        n.is_read = True
        n.read_at = timezone.now()
        n.save(update_fields=["is_read", "read_at"])
    # Only internal links are followed; the target view performs its own authorization check.
    if n.link.startswith("/") and not n.link.startswith("//"):
        return redirect(n.link)
    return redirect("notifications:list")


@require_POST
@login_required
def mark_all_read(request):
    n = request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    messages.success(request, f"{n} notification{'s' if n != 1 else ''} marked as read.")
    return redirect("notifications:list")
