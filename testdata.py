"""
SYNTHETIC test data. Nothing here comes from Maasai Mall or any real vehicle.
All plates start with 'TST'. Arrival patterns are invented (lunchtime and evening peaks, busier weekends)
so that reports, peak hours, repeat vehicles, voids and 'facility full' events can be exercised.
"""
import heapq
import math
import random
from datetime import timedelta

import services as svc
from models import AuditEvent, Meta, ParkingSession, Rate, Slot, Staff, TurnAway, db, now_local

TYPE_WEIGHTS = [("Car", 0.82), ("Motorbike", 0.10), ("Visitor", 0.05), ("Truck", 0.03)]
WEEKDAY = {8: 2, 9: 3, 10: 4, 11: 5, 12: 8, 13: 9, 14: 7, 15: 5, 16: 5, 17: 8, 18: 9, 19: 7, 20: 4, 21: 2}
WEEKEND = {8: 1, 9: 2, 10: 4, 11: 7, 12: 10, 13: 11, 14: 10, 15: 8, 16: 7, 17: 7, 18: 6, 19: 5, 20: 3, 21: 2}


def _plates(rng, n=140):
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    out = set()
    while len(out) < n:
        out.add(f"TST {rng.randint(100, 999)}{rng.choice(letters)}")
    return sorted(out)


def generate(days=21, seed=42, reset=False):
    rng = random.Random(seed)
    if reset:
        ParkingSession.query.delete()
        TurnAway.query.delete()
        for s in Slot.query.filter(Slot.status == "occupied"):
            s.status = "free"
        db.session.commit()
    elif ParkingSession.query.count() > 0:
        return "Sessions already exist; use --reset to replace them."

    slots = Slot.query.filter(Slot.status != "blocked").order_by(Slot.zone, Slot.code).all()
    rates = {r.vehicle_type: r for r in Rate.query.all()}
    attendants = Staff.query.filter_by(role="attendant").all() or Staff.query.all()
    admin = Staff.query.filter_by(role="admin").first()
    plates = _plates(rng)
    plate_w = [1 / (i + 1) ** 0.6 for i in range(len(plates))]  # a few frequent visitors
    now = now_local()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    made = voided = turned = 0

    for back in range(days, 0, -1):
        day0 = today0 - timedelta(days=back)
        weekend = day0.weekday() >= 5
        weights = WEEKEND if weekend else WEEKDAY
        n = rng.randint(85, 115) if weekend else rng.randint(55, 80)
        hours, hw = list(weights), list(weights.values())
        arrivals = sorted(day0 + timedelta(hours=rng.choices(hours, hw)[0], minutes=rng.randint(0, 59)) for _ in range(n))
        busy = []  # heap of (departure, slot_index, plate)
        parked = set()
        for t in arrivals:
            while busy and busy[0][0] <= t:
                _, si, pl = heapq.heappop(busy)
                parked.discard(pl)
            taken = {si for _, si, _ in busy}
            free = [i for i in range(len(slots)) if i not in taken]
            if not free:
                db.session.add(TurnAway(occurred_at=t))
                turned += 1
                continue
            plate = None
            for _ in range(15):
                cand = rng.choices(plates, plate_w)[0]
                if cand not in parked:
                    plate = cand
                    break
            if plate is None:
                continue
            si = free[0]
            vtype = rng.choices([w[0] for w in TYPE_WEIGHTS], [w[1] for w in TYPE_WEIGHTS])[0]
            minutes = rng.randint(2, 9) if rng.random() < 0.08 else int(min(300, max(5, rng.lognormvariate(math.log(70), 0.55))))
            t_out = t + timedelta(minutes=minutes)
            heapq.heappush(busy, (t_out, si, plate))
            parked.add(plate)
            r = rates[vtype]
            sess = ParkingSession(plate_number=plate, vehicle_type=vtype, slot_id=slots[si].id,
                                  time_in=t, time_out=t_out, status="closed",
                                  fee=svc.calculate_fee(t, t_out, r.price_per_hour, r.grace_minutes),
                                  logged_by=rng.choice(attendants).id)
            if rng.random() < 0.01 and admin:
                sess.status, sess.voided_at, sess.voided_by = "voided", t_out + timedelta(minutes=5), admin.id
                sess.void_reason = "Test data: entered in error"
                voided += 1
            db.session.add(sess)
            made += 1

    # a few vehicles "currently parked", so the dashboard has live rows
    active = 0
    for i, minutes_ago in enumerate((12, 25, 47, 66, 95, 140)):
        if i >= len(slots):
            break
        t = now - timedelta(minutes=minutes_ago)
        plate = f"TST {900 + i}{'ABCDEF'[i]}"
        db.session.add(ParkingSession(plate_number=plate, vehicle_type="Car" if i != 3 else "Motorbike",
                                      slot_id=slots[i].id, time_in=t, status="active",
                                      logged_by=rng.choice(attendants).id))
        slots[i].status = "occupied"
        active += 1

    meta = db.session.get(Meta, "data_mode") or Meta(key="data_mode", value="test")
    meta.value = "test"
    db.session.merge(meta)
    db.session.add(AuditEvent(action="seed_test_data", detail=f"{made} sessions, {turned} turn-aways, seed {seed}"))
    db.session.commit()
    return (f"Synthetic test data created: {made} completed sessions over {days} days ({voided} voided), "
            f"{active} vehicles currently parked, {turned} facility-full events.")
