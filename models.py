"""Database models. Times are stored as naive local time (East Africa Time, UTC+3)."""
from datetime import datetime, timedelta, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, text
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()
EAT = timezone(timedelta(hours=3), "EAT")  # Kenya has no daylight saving


def now_local():
    """Current East Africa Time as a naive datetime (what is stored and displayed)."""
    return datetime.now(EAT).replace(tzinfo=None)


class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="attendant")  # attendant | admin
    active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class Rate(db.Model):
    """Charging rule per vehicle type (to be confirmed with the facility)."""
    id = db.Column(db.Integer, primary_key=True)
    vehicle_type = db.Column(db.String(30), unique=True, nullable=False)
    price_per_hour = db.Column(db.Float, nullable=False)
    grace_minutes = db.Column(db.Integer, nullable=False, default=10)


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    zone = db.Column(db.String(30), nullable=False, default="Main")
    status = db.Column(db.String(20), nullable=False, default="free")  # free | occupied | blocked (recorded only)


class ParkingSession(db.Model):
    """
    One visit. The only identifying detail stored about a visiting vehicle is its plate number
    (no names, phone numbers or ID numbers), per the proposal's privacy policy.
    """
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(20), nullable=False, index=True)
    vehicle_type = db.Column(db.String(30), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("slot.id"), nullable=False)
    time_in = db.Column(db.DateTime, nullable=False, default=now_local)
    time_out = db.Column(db.DateTime, nullable=True)
    fee = db.Column(db.Float, nullable=True)  # a CALCULATED fee, not a confirmed payment
    status = db.Column(db.String(20), nullable=False, default="active")  # active | closed | voided
    logged_by = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    voided_by = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    void_reason = db.Column(db.String(200), nullable=True)

    slot = db.relationship("Slot", backref="sessions")
    logger = db.relationship("Staff", foreign_keys=[logged_by])

    __table_args__ = (
        # the database itself refuses two active sessions for one slot or for one plate
        Index("uq_active_slot", "slot_id", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
        Index("uq_active_plate", "plate_number", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )


class TurnAway(db.Model):
    """OPTIONAL: logged when check-in is opened and no slot is free. Keep only if management wants it."""
    id = db.Column(db.Integer, primary_key=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=now_local)


class AuditEvent(db.Model):
    """Who did what, and when."""
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    username = db.Column(db.String(50), nullable=True)
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(300), nullable=True)


class Meta(db.Model):
    """Key/value store (data_mode = 'test' shows a banner that the data is synthetic)."""
    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(200), nullable=False)
