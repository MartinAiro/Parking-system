import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routes  # noqa: E402
from app import create_app, init_db  # noqa: E402
from models import ParkingSession, Slot, Staff, db, now_local  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-key",
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}"})
    with app.app_context():
        init_db(True)
    routes.reset_throttle()
    return app


class Browser:
    """A test client that adds the CSRF token to every POST, like a real browser form would."""
    def __init__(self, app):
        self.app, self.c = app, app.test_client()

    def token(self):
        self.c.get("/login")
        with self.c.session_transaction() as s:
            return s["_csrf"]

    def get(self, url, **kw):
        return self.c.get(url, follow_redirects=kw.pop("follow", True), **kw)

    def post(self, url, data=None, follow=True, csrf=True):
        d = dict(data or {})
        if csrf:
            d.setdefault("csrf_token", self.token())
        return self.c.post(url, data=d, follow_redirects=follow)

    def login(self, username, password):
        return self.post("/login", {"username": username, "password": password})


@pytest.fixture()
def anon(app):
    return Browser(app)


@pytest.fixture()
def admin(app):
    b = Browser(app)
    b.login("admin", "admin123")
    return b


@pytest.fixture()
def attendant(app):
    b = Browser(app)
    b.login("attendant", "attendant123")
    return b


def free_slot_id(app, code="A-01"):
    with app.app_context():
        return Slot.query.filter_by(code=code).first().id


def make_session(app, plate="KXX 100A", slot="A-01", vtype="Car", minutes_ago=30, status="active",
                 fee=None, hours_closed_ago=None):
    """Insert a session directly (bypassing the web form) for report and checkout tests."""
    with app.app_context():
        s = Slot.query.filter_by(code=slot).first()
        t_in = now_local() - timedelta(minutes=minutes_ago)
        sess = ParkingSession(plate_number=plate, vehicle_type=vtype, slot_id=s.id, time_in=t_in,
                              status=status, logged_by=Staff.query.first().id)
        if status == "active":
            s.status = "occupied"
        if status == "closed":
            sess.time_out = t_in + timedelta(minutes=minutes_ago // 2 or 1)
            sess.fee = fee if fee is not None else 100.0
        db.session.add(sess)
        db.session.commit()
        return sess.id
