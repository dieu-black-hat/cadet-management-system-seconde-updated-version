from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("statements.csv", views.export_statements, name="statements_csv"),
    path("assessments.csv", views.export_assessments, name="assessments_csv"),
    path("summary.pdf", views.export_pdf, name="summary_pdf"),
]
