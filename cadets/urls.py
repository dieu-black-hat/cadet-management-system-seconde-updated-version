from django.urls import path

from . import views

app_name = "cadets"

urlpatterns = [
    path("", views.cadet_list, name="list"),
    path("new/", views.cadet_create, name="create"),
    path("import/", views.cadet_import, name="import"),
    path("export.csv", views.cadet_export, name="export"),
    path("<int:pk>/", views.cadet_detail, name="detail"),
    path("<int:pk>/edit/", views.cadet_edit, name="edit"),
    path("<int:pk>/photo/", views.cadet_photo, name="photo"),
    path("<int:pk>/reassign/", views.cadet_reassign, name="reassign"),
    path("<int:pk>/archive/", views.cadet_archive, name="archive"),
    path("<int:pk>/override/", views.cadet_override, name="override"),
    path("<int:pk>/override/clear/", views.cadet_clear_override, name="clear_override"),
    path("organisation/", views.org_overview, name="org"),
    path("organisation/<str:kind>/new/", views.org_edit, name="org_create"),
    path("organisation/<str:kind>/<int:pk>/", views.org_edit, name="org_edit"),
]
