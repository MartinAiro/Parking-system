"""T41-T55: reports, export, audit, API, time handling, test data."""
from datetime import datetime, timedelta, timezone
import services as svc
import testdata
from conftest import make_session
from models import AuditEvent, Meta, ParkingSession, Slot, db, now_local


def test_T41_reports_figures_exclude_voided_and_count_repeats(app, admin):
    make_session(app, plate="AAA 111A", slot="A-01", status="closed", fee=100, minutes_ago=120)
    make_session(app, plate="AAA 111A", slot="A-02", status="closed", fee=200, minutes_ago=100, vtype="Truck")
    v = make_session(app, plate="BBB 222B", slot="A-03", status="closed", fee=999, minutes_ago=80)
    admin.post(f"/session/{v}/void", {"reason": "Entered in error"})
    with app.app_context():
        r = svc.build_reports()
    assert r["total_fees"] == 300 and r["completed"] == 2 and r["voided"] == 1
    assert r["by_type"]["Car"]["count"] == 1 and r["by_type"]["Truck"]["fees"] == 200
    assert r["repeat"] == [("AAA 111A", 2)]


def test_T42_reports_page_renders_with_calculated_wording(app, admin):
    make_session(app, status="closed")
    r = admin.get("/reports")
    assert b"Total fees calculated" in r.data and b"not payments received" in r.data


def test_T43_occupancy_excludes_blocked_slots(app):
    with app.app_context():
        Slot.query.filter_by(code="A-01").first().status = "blocked"
        Slot.query.filter_by(code="A-02").first().status = "occupied"
        db.session.commit()
        o = svc.occupancy_counts()
    assert (o["total"], o["blocked"], o["usable"], o["occupied"], o["free"]) == (20, 1, 19, 1, 18)


def test_T44_csv_export_content_and_formula_guard(app, admin):
    make_session(app, plate="AAA 111A", status="closed", fee=150)
    body = admin.get("/sessions/export.csv").data.decode()
    assert body.splitlines()[0].startswith("id,plate,vehicle_type,slot") and "150.00" in body
    from routes import _csv_safe
    assert _csv_safe("=1+1") == "'=1+1" and _csv_safe("KXX 100A") == "KXX 100A"


def test_T45_sessions_page_filters_and_attendant_sees_today_only(app, attendant, admin):
    make_session(app, plate="AAA 111A", slot="A-01")
    assert b"AAA 111A" in attendant.get("/sessions").data
    assert b"No sessions match" in admin.get("/sessions?q=ZZZ").data
    assert b"Date must look like" in admin.get("/sessions?date=not-a-date").data


def test_T46_audit_log_records_key_actions(app, admin):
    sid = make_session(app, minutes_ago=90)
    admin.post(f"/exit/{sid}")
    admin.post("/rates", {"vehicle_type": "Bus", "price_per_hour": "300", "grace_minutes": "10"})
    with app.app_context():
        actions = {e.action for e in AuditEvent.query.all()}
    assert {"login", "check_out", "rate_saved"} <= actions
    assert b"check_out" in admin.get("/audit").data


def test_T47_api_occupancy_json(app, attendant):
    j = attendant.get("/api/occupancy").get_json()
    assert j == {"total": 20, "occupied": 0, "free": 20, "blocked": 0}


def test_T48_times_are_east_africa_time_not_utc():
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((now_local() - utc - timedelta(hours=3)).total_seconds()) < 5


def test_T49_error_pages_are_friendly(anon):
    r = anon.get("/no-such-page")
    assert r.status_code == 404 and b"Page not found" in r.data


def test_T50_test_data_generator_makes_labelled_synthetic_data(app, admin):
    with app.app_context():
        msg = testdata.generate(days=5, seed=1)
        assert "Synthetic test data" in msg
        assert ParkingSession.query.filter(~ParkingSession.plate_number.like("TST %")).count() == 0
        assert db.session.get(Meta, "data_mode").value == "test"
        assert "already exist" in testdata.generate(days=5, seed=1)
        assert svc.build_reports()["completed"] > 100
    assert b"TEST DATA" in admin.get("/dashboard").data


def test_T51_test_data_never_double_books(app):
    with app.app_context():
        testdata.generate(days=10, seed=7)
        rows = ParkingSession.query.filter(ParkingSession.status != "voided").all()
        by_slot = {}
        for s in rows:
            by_slot.setdefault(s.slot_id, []).append(s)
        for lst in by_slot.values():
            lst.sort(key=lambda s: s.time_in)
            for a, b in zip(lst, lst[1:]):
                assert (a.time_out or datetime.max) <= b.time_in
