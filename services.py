"""Business rules: validation, fee calculation and report queries (no web code here)."""
import math
import re
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func

from models import db, Slot, ParkingSession, Rate, TurnAway, now_local

PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 \-]{2,14}$")
VEHICLE_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 \-]{1,29}$")
SLOT_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{0,19}$")
USERNAME_RE = re.compile(r"^[a-z0-9._\-]{3,30}$")
MAX_PRICE_PER_HOUR = 100000.0
MAX_GRACE_MINUTES = 240
MIN_PASSWORD_LENGTH = 8
DEFAULT_PASSWORDS = {"admin123", "attendant123"}  # demo passwords, flagged until changed


class MissingRate(Exception):
    """No rate is configured for a vehicle type."""


def normalize_plate(raw):
    return re.sub(r"\s+", " ", (raw or "").strip().upper())


def validate_plate(plate):
    if not plate:
        return "Plate number is required."
    if not PLATE_RE.match(plate):
        return "Plate number must be 3 to 15 characters: letters, digits, spaces or hyphens."
    return None


def validate_rate(vehicle_type, price_raw, grace_raw):
    errors = []
    vt = re.sub(r"\s+", " ", (vehicle_type or "").strip())
    if not VEHICLE_TYPE_RE.match(vt):
        errors.append("Vehicle type must be 2 to 30 characters, starting with a letter.")
    try:
        price = float(price_raw)
        if not math.isfinite(price) or price < 0 or price > MAX_PRICE_PER_HOUR:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(f"Price per hour must be a number from 0 to {MAX_PRICE_PER_HOUR:,.0f}.")
        price = None
    try:
        grace = int(str(grace_raw).strip())
        if grace < 0 or grace > MAX_GRACE_MINUTES:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(f"Grace period must be a whole number of minutes from 0 to {MAX_GRACE_MINUTES}.")
        grace = None
    return (vt, price, grace), errors


def validate_slot(code_raw, zone_raw):
    code = (code_raw or "").strip().upper()
    zone = re.sub(r"\s+", " ", (zone_raw or "").strip()) or "Main"
    errors = []
    if not SLOT_CODE_RE.match(code):
        errors.append("Slot code must be 1 to 20 letters, digits or hyphens.")
    if len(zone) > 30:
        errors.append("Zone name must be 30 characters or fewer.")
    return (code, zone), errors


def validate_password(pw, confirm=None):
    if len(pw or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if confirm is not None and pw != confirm:
        return "The two passwords do not match."
    if (pw or "").lower() in {p.lower() for p in DEFAULT_PASSWORDS}:
        return "Choose a password that is not one of the demo passwords."
    return None


def calculate_fee(time_in, time_out, price_per_hour, grace_minutes):
    """
    CALCULATED fee (an amount owed, not a payment received). Whole minutes are counted. A stay
    within the grace period is free; otherwise it is charged per started hour, minimum one hour.
    """
    seconds = (time_out - time_in).total_seconds()
    minutes = int(max(seconds, 0) // 60)
    if minutes <= grace_minutes:
        return 0.0
    return round(max(1, math.ceil(minutes / 60)) * price_per_hour, 2)


def rate_for(vehicle_type):
    rate = Rate.query.filter_by(vehicle_type=vehicle_type).first()
    if rate is None:
        raise MissingRate(vehicle_type)
    return rate


def fee_for_session(sess, time_out):
    rate = rate_for(sess.vehicle_type)
    return calculate_fee(sess.time_in, time_out, rate.price_per_hour, rate.grace_minutes)


def occupancy_counts():
    total = Slot.query.count()
    blocked = Slot.query.filter_by(status="blocked").count()
    occupied = Slot.query.filter_by(status="occupied").count()
    usable = total - blocked
    return dict(total=total, blocked=blocked, usable=usable, occupied=occupied,
                free=usable - occupied, rate=(occupied / usable * 100) if usable else 0.0)


def build_reports(day_limit=14):
    """All figures exclude voided sessions."""
    closed = ParkingSession.query.filter_by(status="closed").all()
    live = ParkingSession.query.filter(ParkingSession.status != "voided").all()
    durations = [(s.time_out - s.time_in).total_seconds() / 60 for s in closed]
    by_type = defaultdict(lambda: {"count": 0, "fees": 0.0})
    by_day = defaultdict(float)
    for s in closed:
        by_type[s.vehicle_type]["count"] += 1
        by_type[s.vehicle_type]["fees"] += s.fee or 0
        by_day[s.time_out.strftime("%Y-%m-%d")] += s.fee or 0
    by_hour = {h: 0 for h in range(24)}
    plates = defaultdict(int)
    for s in live:
        by_hour[s.time_in.hour] += 1
        plates[s.plate_number] += 1
    repeat = sorted(((p, c) for p, c in plates.items() if c > 1), key=lambda x: (-x[1], x[0]))[:10]
    return dict(total_fees=sum(s.fee or 0 for s in closed), completed=len(closed),
                avg_stay=(sum(durations) / len(durations)) if durations else 0,
                by_type=dict(by_type), by_day=dict(sorted(by_day.items())[-day_limit:]),
                by_hour=by_hour, repeat=repeat,
                voided=ParkingSession.query.filter_by(status="voided").count(),
                turn_aways=TurnAway.query.count(), occupancy=occupancy_counts())


def fees_today():
    start = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    return (db.session.query(func.coalesce(func.sum(ParkingSession.fee), 0.0))
            .filter(ParkingSession.status == "closed", ParkingSession.time_out >= start,
                    ParkingSession.time_out < start + timedelta(days=1)).scalar()) or 0.0
