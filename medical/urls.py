from django.urls import path

from . import views

app_name = "medical"

urlpatterns = [
    path("", views.record_list, name="list"),
    path("new/", views.record_create, name="create"),
    path("cadet/<int:cadet_id>/", views.cadet_file, name="cadet"),
    path("<int:pk>/", views.record_detail, name="detail"),
    path("<int:pk>/edit/", views.record_edit, name="edit"),
    path("<int:pk>/documents/", views.attachment_upload, name="attachment_upload"),
    path("<int:pk>/documents/<int:att_id>/", views.attachment_download, name="attachment_download"),
]
