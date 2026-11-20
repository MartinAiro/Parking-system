"""T27-T45: corrections, voids, rates, slots, staff."""
from conftest import make_session, free_slot_id
from models import ParkingSession, Rate, Slot, Staff, db


def test_T27_attendant_can_correct_plate_of_parked_vehicle(app, attendant):
    sid = make_session(app, plate="KXX 100A")
    assert b"corrected" in attendant.post(f"/session/{sid}/plate", {"plate_number": "kxx 100b"}).data
    with app.app_context():
        assert db.session.get(ParkingSession, sid).plate_number == "KXX 100B"


def test_T28_plate_correction_rejects_duplicates_invalid_and_closed(app, attendant):
    a = make_session(app, plate="AAA 111A", slot="A-01")
    make_session(app, plate="BBB 222B", slot="A-02")
    assert b"already checked in" in attendant.post(f"/session/{a}/plate", {"plate_number": "BBB 222B"}).data
    assert b"3 to 15" in attendant.post(f"/session/{a}/plate", {"plate_number": "!!"}).data
    closed = make_session(app, plate="CCC 333C", slot="A-03", status="closed")
    assert b"Only a vehicle that is still parked" in attendant.get(f"/session/{closed}/plate").data


def test_T29_admin_void_active_session_frees_slot(app, admin):
    sid = make_session(app, plate="AAA 111A", slot="A-01")
    assert b"voided" in admin.post(f"/session/{sid}/void", {"reason": "Entered in error"}).data
    with app.app_context():
        s = db.session.get(ParkingSession, sid)
        assert s.status == "voided" and s.void_reason == "Entered in error"
        assert Slot.query.filter_by(code="A-01").first().status == "free"


def test_T30_void_needs_reason_and_cannot_repeat(app, admin):
    sid = make_session(app)
    assert b"reason" in admin.post(f"/session/{sid}/void", {"reason": "x"}).data
    admin.post(f"/session/{sid}/void", {"reason": "Entered in error"})
    assert b"Already voided" in admin.post(f"/session/{sid}/void", {"reason": "again please"}).data


def test_T31_attendant_cannot_void(app, attendant):
    sid = make_session(app)
    assert b"Administrators only" in attendant.post(f"/session/{sid}/void", {"reason": "nope nope"}).data
    with app.app_context():
        assert db.session.get(ParkingSession, sid).status == "active"


def test_T32_rate_validation(app, admin):
    bad = [("Bus", "-50", "10"), ("Bus", "abc", "10"), ("Bus", "1000000000", "10"), ("Bus", "nan", "10"),
           ("Bus", "100", "-5"), ("Bus", "100", "999"), ("Bus", "100", "x"), ("", "100", "10"), ("1Bus", "100", "10")]
    for vt, price, grace in bad:
        admin.post("/rates", {"vehicle_type": vt, "price_per_hour": price, "grace_minutes": grace})
    with app.app_context():
        assert Rate.query.filter_by(vehicle_type="Bus").count() == 0


def test_T33_rate_add_and_update(app, admin):
    admin.post("/rates", {"vehicle_type": "Bus", "price_per_hour": "300", "grace_minutes": "15"})
    admin.post("/rates", {"vehicle_type": "Bus", "price_per_hour": "350", "grace_minutes": "20"})
    with app.app_context():
        r = Rate.query.filter_by(vehicle_type="Bus").one()
        assert (r.price_per_hour, r.grace_minutes) == (350, 20)


def test_T34_slot_validation_and_duplicates(app, admin):
    admin.post("/slots", {"code": "Z-01", "zone": "Test"})
    assert b"already exists" in admin.post("/slots", {"code": "z-01", "zone": "Test"}).data
    assert b"1 to 20" in admin.post("/slots", {"code": "bad code!", "zone": "Test"}).data
    with app.app_context():
        assert Slot.query.filter_by(code="Z-01").count() == 1


def test_T35_block_and_unblock_slot_but_not_when_occupied(app, admin):
    sid = free_slot_id(app, "A-05")
    admin.post(f"/slots/{sid}/toggle")
    with app.app_context():
        assert Slot.query.filter_by(code="A-05").first().status == "blocked"
    admin.post(f"/slots/{sid}/toggle")
    with app.app_context():
        assert Slot.query.filter_by(code="A-05").first().status == "free"
    make_session(app, slot="A-06")
    assert b"cannot be blocked" in admin.post(f"/slots/{free_slot_id(app, 'A-06')}/toggle").data


def test_T36_blocked_slot_not_offered_at_checkin(app, admin):
    admin.post(f"/slots/{free_slot_id(app, 'A-01')}/toggle")
    assert b">A-01 " not in admin.get("/entry").data


def test_T37_staff_add_and_validation(app, admin):
    ok = {"name": "New Attendant", "username": "new.att", "role": "attendant", "password": "Good-pass-1", "confirm": "Good-pass-1"}
    assert b"created" in admin.post("/staff", ok).data
    assert b"taken" in admin.post("/staff", ok).data
    assert b"Username" in admin.post("/staff", {**ok, "username": "Bad Name"}).data
    assert b"at least 8" in admin.post("/staff", {**ok, "username": "other", "password": "x", "confirm": "x"}).data


def test_T38_new_account_can_log_in(app, admin, anon):
    admin.post("/staff", {"name": "New Att", "username": "newatt", "role": "attendant", "password": "Good-pass-1", "confirm": "Good-pass-1"})
    assert b"Dashboard" in anon.login("newatt", "Good-pass-1").data


def test_T39_cannot_deactivate_self_or_last_admin(app, admin):
    with app.app_context():
        me = Staff.query.filter_by(username="admin").first().id
    assert b"cannot deactivate your own" in admin.post(f"/staff/{me}/toggle").data


def test_T40_deactivate_attendant_blocks_login_and_reset_password_works(app, admin, anon):
    with app.app_context():
        att = Staff.query.filter_by(username="attendant").first().id
    admin.post(f"/staff/{att}/password", {"password": "Reset-pass-9", "confirm": "Reset-pass-9"})
    assert b"Dashboard" in anon.login("attendant", "Reset-pass-9").data
    admin.post(f"/staff/{att}/toggle")
    other = type(anon)(app)
    assert b"Invalid" in other.login("attendant", "Reset-pass-9").data
