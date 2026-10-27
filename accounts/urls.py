from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/sent/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/active/", views.user_set_active, name="user_set_active"),
    path("users/<int:pk>/suspend/", views.user_suspend, name="user_suspend"),
    path("users/<int:pk>/reinstate/", views.user_reinstate, name="user_reinstate"),
    path("users/<int:pk>/invite/", views.user_resend_invite, name="user_resend_invite"),
    path("users/<int:pk>/grant/", views.user_grant, name="user_grant"),
    path("users/<int:pk>/grant/<int:grant_id>/revoke/", views.user_revoke, name="user_revoke"),
    path("users/<int:pk>/assign/", views.user_assign, name="user_assign"),
    path("users/<int:pk>/assign/<int:assignment_id>/end/", views.user_unassign, name="user_unassign"),
    path("permissions/", views.permission_matrix, name="matrix"),
]
