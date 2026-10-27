from django.urls import path

from . import views

app_name = "discipline"

urlpatterns = [
    path("", views.statement_list, name="list"),
    path("mine/", views.my_statements, name="mine"),
    path("queue/", views.review_queue, name="queue"),
    path("new/", views.statement_create, name="create"),
    path("<int:pk>/", views.statement_detail, name="detail"),
    path("<int:pk>/edit/", views.statement_edit, name="edit"),
    path("<int:pk>/decide/", views.statement_transition, name="transition"),
    path("<int:pk>/comment/", views.comment_add, name="comment"),
    path("<int:pk>/attachments/", views.attachment_upload, name="attachment_upload"),
    path("<int:pk>/attachments/<int:att_id>/", views.attachment_download, name="attachment_download"),
    path("grading/", views.policy_list, name="policy_list"),
    path("grading/new-version/", views.policy_new_version, name="policy_new"),
    path("grading/recalculate/", views.policy_recalculate, name="policy_recalculate"),
    path("grading/<int:pk>/", views.policy_detail, name="policy_detail"),
    path("grading/<int:pk>/edit/", views.policy_edit, name="policy_edit"),
    path("grading/<int:pk>/activate/", views.policy_activate, name="policy_activate"),
]
