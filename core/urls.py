from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("features/", views.services, name="services"),
    path("contact/", views.contact, name="contact"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("search/", views.search, name="search"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/messages/", views.contact_messages, name="contact_messages"),
    path("settings/messages/<int:pk>/handled/", views.contact_message_handled, name="contact_message_handled"),
]
