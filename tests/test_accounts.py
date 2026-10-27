import re

import pytest
from django.core import mail

from accounts.models import LoginAttempt, PermissionGrant, User
from audit.models import AuditEvent
from core.permissions import Role

from .conftest import PASSWORD


def post_login(client, email, password):
    return client.post("/accounts/login/", {"username": email, "password": password})


def test_valid_and_invalid_login(client, org):
    r = post_login(client, "ins@test.local", "wrong-password")
    assert r.status_code == 200 and "incorrect" in r.content.decode()
    assert AuditEvent.objects.filter(event_type="auth.login_failed").exists()
    r = post_login(client, "INS@test.local", PASSWORD)  # case-insensitive email
    assert r.status_code == 302 and r["Location"] == "/dashboard/"
    assert AuditEvent.objects.filter(event_type="auth.login", outcome="SUCCESS").exists()


def test_logout_requires_post_and_ends_session(client, org):
    post_login(client, "ins@test.local", PASSWORD)
    assert client.get("/accounts/logout/").status_code == 405
    client.post("/accounts/logout/")
    assert client.get("/dashboard/").status_code == 302


def test_lockout_after_repeated_failures(client, org, settings):
    for _ in range(settings.LOGIN_MAX_FAILURES):
        post_login(client, "ins@test.local", "nope")
    r = post_login(client, "ins@test.local", PASSWORD)  # even the right password is refused while locked
    assert r.status_code == 429
    assert LoginAttempt.objects.filter(email="ins@test.local", successful=False).count() == settings.LOGIN_MAX_FAILURES


def test_suspended_and_deactivated_accounts(client, org, login):
    u = org["users"]["instructor"]
    c = login(u)
    u.is_suspended = True
    u.save()
    r = c.get("/dashboard/")  # existing session is terminated immediately
    assert r.status_code == 302 and "/accounts/login/" in r["Location"]
    assert post_login(client, u.email, PASSWORD).status_code == 200
    u.is_suspended = False
    u.is_active = False
    u.save()
    assert post_login(client, u.email, PASSWORD).status_code == 200


def test_password_reset_is_generic_and_single_use(client, org):
    r1 = client.post("/accounts/password/reset/", {"email": "nobody@test.local"})
    r2 = client.post("/accounts/password/reset/", {"email": "ins@test.local"})
    assert r1.status_code == r2.status_code == 302 and r1["Location"] == r2["Location"]
    assert len(mail.outbox) == 1
    link = re.search(r"(/accounts/password/reset/[^/\s]+/[^/\s]+/)", mail.outbox[0].body).group(1)
    r = client.get(link, follow=True)
    form_url = r.redirect_chain[-1][0]
    new = "N3w-Strong-Pass!"
    r = client.post(form_url, {"new_password1": new, "new_password2": new})
    assert r.status_code == 302
    assert User.objects.get(email="ins@test.local").check_password(new)
    r = client.get(link, follow=True)  # token cannot be reused
    assert "can't be used" in r.content.decode()


def test_admin_invites_user_without_choosing_password(org, login):
    c = login(org["users"]["admin"])
    r = c.post("/accounts/users/new/", {"first_name": "New", "last_name": "Person", "email": "new@test.local",
                                         "role": Role.INSTRUCTOR, "rank": "Sgt", "service_number": "", "phone": ""})
    assert r.status_code == 302
    u = User.objects.get(email="new@test.local")
    assert not u.has_usable_password()
    assert "reset" in mail.outbox[-1].body and "new@test.local" in mail.outbox[-1].to


def test_non_admin_cannot_create_or_escalate(org, login):
    c = login(org["users"]["cc_a"])
    r = c.post("/accounts/users/new/", {"first_name": "X", "last_name": "Y", "email": "x@test.local",
                                         "role": Role.ADMIN})
    assert r.status_code == 403
    me = org["users"]["cc_a"]
    r = c.post(f"/accounts/users/{me.pk}/grant/", {"permission": "users.manage", "reason": "please"})
    assert r.status_code == 403
    assert not User.objects.filter(email="x@test.local").exists()
    assert not PermissionGrant.objects.filter(user=me).exists()


def test_admin_cannot_deactivate_self(org, login):
    admin = org["users"]["admin"]
    login(admin).post(f"/accounts/users/{admin.pk}/active/", {"active": "0"})
    admin.refresh_from_db()
    assert admin.is_active


def test_permission_grant_and_revoke(org, login):
    admin, pc = org["users"]["admin"], org["users"]["pc_a1"]
    c = login(admin)
    assert not pc.has_ocms_perm("reports.export")
    c.post(f"/accounts/users/{pc.pk}/grant/", {"permission": "reports.export", "reason": "Quarterly briefing"})
    pc = User.objects.get(pk=pc.pk)
    assert pc.has_ocms_perm("reports.export")
    g = PermissionGrant.objects.get(user=pc)
    c.post(f"/accounts/users/{pc.pk}/grant/{g.pk}/revoke/")
    assert not User.objects.get(pk=pc.pk).has_ocms_perm("reports.export")
    assert AuditEvent.objects.filter(event_type__in=["permission.granted", "permission.revoked"]).count() == 2


def test_role_change_takes_effect(org, login):
    admin, ins = org["users"]["admin"], org["users"]["instructor"]
    c = login(ins)
    assert c.get("/reports/").status_code == 403
    login(admin).post(f"/accounts/users/{ins.pk}/edit/", {
        "first_name": ins.first_name, "last_name": "T", "email": ins.email, "role": Role.COMPANY_COMMANDER,
        "rank": "", "service_number": "", "phone": ""})
    assert c.get("/reports/").status_code == 200


def test_unit_assignment_controls_scope(org, login):
    admin, ins = org["users"]["admin"], org["users"]["instructor"]
    b1 = org["cadets"]["b1"]
    assert login(ins).get(f"/cadets/{b1.pk}/").status_code == 403
    login(admin).post(f"/accounts/users/{ins.pk}/assign/", {"platoon": org["platoons"]["b1"].pk})
    assert login(ins).get(f"/cadets/{b1.pk}/").status_code == 200


@pytest.mark.parametrize("role", ["admin", "instructor", "pc_a1", "cc_a", "doctor", "auditor"])
def test_every_role_dashboard_renders(org, login, role):
    r = login(org["users"][role]).get("/dashboard/")
    assert r.status_code == 200 and r["Cache-Control"] == "no-store, private"
    assert "Content-Security-Policy" in r


def test_public_pages_and_contact(client, db):
    for p in ["/", "/about/", "/features/", "/contact/", "/accounts/login/", "/accounts/password/reset/"]:
        assert client.get(p).status_code == 200
    r = client.post("/contact/", {"name": "A", "email": "bad", "subject": "Hi", "message": "Hello"})
    assert r.status_code == 200  # invalid email shown again
    r = client.post("/contact/", {"name": "A", "email": "a@b.rw", "subject": "Hi", "message": "Hello there"})
    assert r.status_code == 302
