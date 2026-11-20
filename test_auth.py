"""T01-T10: authentication, access control, CSRF, password rules."""
import re
from models import AuditEvent, Staff, db
import routes
from conftest import Browser


def test_T01_login_success_shows_dashboard(anon):
    r = anon.login("admin", "admin123")
    assert b"Dashboard" in r.data and b"Maasai Mall" in r.data


def test_T02_wrong_password_rejected(anon):
    r = anon.login("admin", "nope")
    assert b"Invalid username or password" in r.data


def test_T03_deactivated_user_cannot_log_in(app, anon):
    with app.app_context():
        Staff.query.filter_by(username="attendant").first().active = False
        db.session.commit()
    assert b"Invalid username or password" in anon.login("attendant", "attendant123").data


def test_T04_lockout_after_five_failures(app, anon):
    for _ in range(5):
        anon.login("admin", "bad")
    r = anon.c.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": anon.token()})
    assert r.status_code == 429


def test_T05_protected_pages_redirect_to_login(anon):
    for url in ("/dashboard", "/entry", "/sessions", "/reports", "/slots", "/api/occupancy"):
        r = anon.get(url, follow=False)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_T06_logout_ends_session(admin):
    admin.get("/logout")
    assert "/login" in admin.get("/dashboard", follow=False).headers["Location"]


def test_T07_post_without_csrf_token_is_refused(app, admin):
    r = admin.post("/rates", {"vehicle_type": "Bus", "price_per_hour": "10", "grace_minutes": "5"}, csrf=False)
    assert r.status_code == 400
    r = admin.c.post("/entry", data={"csrf_token": "forged"})
    assert r.status_code == 400


def test_T08_demo_password_warning_clears_after_change(admin):
    assert b"demo password" in admin.get("/dashboard").data
    admin.post("/account/password", {"current": "admin123", "new": "Str0ng-pass!", "confirm": "Str0ng-pass!"})
    assert b"demo password" not in admin.get("/dashboard").data


def test_T09_password_change_validation(admin):
    cases = [("wrong", "Str0ng-pass!", "Str0ng-pass!", b"current password is incorrect"),
             ("admin123", "short", "short", b"at least 8"),
             ("admin123", "Str0ng-pass!", "different!!", b"do not match"),
             ("admin123", "admin123", "admin123", b"not one of the demo passwords")]
    for cur, new, conf, msg in cases:
        assert msg in admin.post("/account/password", {"current": cur, "new": new, "confirm": conf}).data


def test_T10_attendant_blocked_from_admin_pages(attendant):
    for url in ("/slots", "/rates", "/staff", "/reports", "/audit", "/sessions/export.csv"):
        r = attendant.get(url)
        assert b"Administrators only" in r.data, url
    assert b"Reports" not in attendant.get("/dashboard").data.split(b"</header>")[0]


def test_T11_audit_records_logins(app, admin):
    with app.app_context():
        assert AuditEvent.query.filter_by(action="login").count() == 1
