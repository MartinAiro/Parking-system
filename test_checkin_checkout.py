"""T12-T26: check-in rules, slot allocation, fee calculation, check-out."""
from datetime import datetime, timedelta
import pytest
from sqlalchemy.exc import IntegrityError
import services as svc
from conftest import free_slot_id, make_session
from models import ParkingSession, Rate, Slot, TurnAway, db


def checkin(b, app, plate="kda 123b", slot="A-01", vtype="Car"):
    return b.post("/entry", {"plate_number": plate, "vehicle_type": vtype, "slot_id": free_slot_id(app, slot)})


def test_T12_checkin_normalises_plate_and_occupies_slot(app, attendant):
    r = checkin(attendant, app)
    assert b"KDA 123B checked in to slot A-01" in r.data
    with app.app_context():
        assert Slot.query.filter_by(code="A-01").first().status == "occupied"
        assert ParkingSession.query.one().plate_number == "KDA 123B"


@pytest.mark.parametrize("plate", ["", "   ", "X" * 500, "<script>", "A", "AB", "KD@ 123", "-ABC123"])
def test_T13_invalid_plates_rejected(app, attendant, plate):
    checkin(attendant, app, plate=plate)
    with app.app_context():
        assert ParkingSession.query.count() == 0


def test_T14_same_plate_cannot_be_parked_twice(app, attendant):
    checkin(attendant, app, slot="A-01")
    r = checkin(attendant, app, slot="A-02")
    assert b"already checked in (slot A-01)" in r.data
    with app.app_context():
        assert ParkingSession.query.count() == 1


def test_T15_occupied_slot_cannot_be_reused(app, attendant):
    checkin(attendant, app, plate="AAA 111A", slot="A-01")
    r = checkin(attendant, app, plate="BBB 222B", slot="A-01")
    assert b"not free" in r.data


def test_T16_vehicle_type_without_rate_rejected(app, attendant):
    r = checkin(attendant, app, vtype="Hovercraft")
    assert b"vehicle type that has a rate" in r.data


def test_T17_database_refuses_two_active_sessions_for_one_slot(app):
    make_session(app, plate="AAA 111A", slot="A-03")
    with app.app_context():
        s = Slot.query.filter_by(code="A-03").first()
        db.session.add(ParkingSession(plate_number="BBB 222B", vehicle_type="Car", slot_id=s.id, status="active"))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_T18_facility_full_disables_checkin_and_logs_once(app, attendant):
    with app.app_context():
        Slot.query.update({"status": "occupied"})
        db.session.commit()
    r = attendant.get("/entry")
    assert b"Check-in is disabled" in r.data
    attendant.get("/entry"); attendant.get("/entry")
    with app.app_context():
        assert TurnAway.query.count() == 1  # throttled to one per minute


@pytest.mark.parametrize("minutes,expected", [(0, 0), (1, 0), (10, 0), (11, 100), (59, 100), (60, 100),
                                              (61, 200), (120, 200), (121, 300), (600, 1000)])
def test_T19_fee_boundaries_car(minutes, expected):
    t = datetime(2026, 1, 1, 8)
    assert svc.calculate_fee(t, t + timedelta(minutes=minutes), 100, 10) == expected


def test_T20_fee_ignores_partial_minute_and_negative_duration():
    t = datetime(2026, 1, 1, 8)
    assert svc.calculate_fee(t, t + timedelta(minutes=60, seconds=59), 100, 10) == 100
    assert svc.calculate_fee(t, t - timedelta(minutes=30), 100, 10) == 0


def test_T21_zero_price_rate_gives_zero_fee():
    t = datetime(2026, 1, 1, 8)
    assert svc.calculate_fee(t, t + timedelta(hours=5), 0, 10) == 0


def test_T22_checkout_closes_session_frees_slot_stores_fee(app, attendant):
    sid = make_session(app, plate="KXX 100A", slot="A-01", minutes_ago=95)
    r = attendant.post(f"/exit/{sid}")
    assert b"Calculated fee: 200.00" in r.data and b"collect payment separately" in r.data
    with app.app_context():
        s = db.session.get(ParkingSession, sid)
        assert s.status == "closed" and s.fee == 200 and s.time_out is not None
        assert Slot.query.filter_by(code="A-01").first().status == "free"


def test_T23_second_checkout_is_blocked(app, attendant):
    sid = make_session(app, minutes_ago=95)
    attendant.post(f"/exit/{sid}")
    assert b"not active" in attendant.post(f"/exit/{sid}").data


def test_T24_checkout_preview_says_system_does_not_process_payment(app, attendant):
    sid = make_session(app, minutes_ago=30)
    r = attendant.get(f"/exit/{sid}")
    assert b"Calculated fee" in r.data and b"does not process payment" in r.data


def test_T25_missing_rate_at_checkout_leaves_session_active(app, attendant):
    sid = make_session(app, vtype="Truck", minutes_ago=90)
    with app.app_context():
        Rate.query.filter_by(vehicle_type="Truck").delete()
        db.session.commit()
    assert b"No rate is configured for Truck" in attendant.get(f"/exit/{sid}").data
    with app.app_context():
        assert db.session.get(ParkingSession, sid).status == "active"


def test_T26_unknown_session_gives_friendly_404(attendant):
    r = attendant.get("/exit/99999")
    assert r.status_code == 404 and b"Page not found" in r.data
