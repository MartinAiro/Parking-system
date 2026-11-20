"""Web routes: login, dashboard, check in/out, sessions, slots, rates, staff, reports, audit."""
import csv
import hmac
import io
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from sqlalchemy.exc import IntegrityError

import services as svc
from models import (AuditEvent, Meta, ParkingSession, Rate, Slot, Staff, TurnAway, db, now_local)

bp = Blueprint("main", __name__)
_failed = {}  # username -> failure timestamps (in memory; resets on restart)


def reset_throttle():
    _failed.clear()


def audit(action, detail=""):
    db.session.add(AuditEvent(staff_id=session.get("staff_id"), username=session.get("username"),
                              action=action, detail=(detail or "")[:300]))


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if "staff_id" not in session:
            return redirect(url_for("main.login"))
        staff = db.session.get(Staff, session["staff_id"])
        if staff is None or not staff.active:
            session.clear()
            flash("Your account is no longer active.", "error")
            return redirect(url_for("main.login"))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if session.get("role") != "admin":
            flash("Administrators only.", "error")
            return redirect(url_for("main.dashboard"))
        return view(*a, **kw)
    return wrapped


@bp.before_request
def csrf_protect():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    if request.method == "POST":
        if not hmac.compare_digest(request.form.get("csrf_token", ""), session["_csrf"]):
            abort(400)


@bp.app_context_processor
def inject_globals():
    mode = db.session.get(Meta, "data_mode")
    return {"csrf_token": lambda: session.get("_csrf", ""),
            "current_role": session.get("role"), "current_name": session.get("name"),
            "facility_name": current_app.config["FACILITY_NAME"],
            "weak_password": bool(session.get("weak_pw")),
            "test_data_mode": bool(mode and mode.value == "test")}


def _locked(username):
    cfg = current_app.config
    now = time.time()
    _failed[username] = [t for t in _failed.get(username, []) if now - t < cfg["LOCKOUT_SECONDS"]]
    return len(_failed[username]) >= cfg["MAX_LOGIN_ATTEMPTS"]


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard") if "staff_id" in session else url_for("main.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        if _locked(username):
            flash("Too many failed attempts. Please wait a few minutes and try again.", "error")
            return render_template("login.html"), 429
        staff = Staff.query.filter_by(username=username).first()
        if staff and staff.active and staff.check_password(password):
            _failed.pop(username, None)
            session.clear()
            session["_csrf"] = secrets.token_hex(16)
            session.permanent = True
            session.update(staff_id=staff.id, username=staff.username, name=staff.name,
                           role=staff.role, weak_pw=password in svc.DEFAULT_PASSWORDS)
            audit("login")
            db.session.commit()
            return redirect(url_for("main.dashboard"))
        _failed.setdefault(username, []).append(time.time())
        audit("login_failed", username[:50])
        db.session.commit()
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    if "staff_id" in session:
        audit("logout")
        db.session.commit()
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        staff = db.session.get(Staff, session["staff_id"])
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not staff.check_password(request.form.get("current", "")):
            err = "Your current password is incorrect."
        else:
            err = svc.validate_password(new, confirm)
        if err:
            flash(err, "error")
        else:
            staff.set_password(new)
            session["weak_pw"] = False
            audit("password_changed")
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("account.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    active = ParkingSession.query.filter_by(status="active").order_by(ParkingSession.time_in.desc()).all()
    return render_template("dashboard.html", occ=svc.occupancy_counts(), active=active,
                           fees_today=svc.fees_today())


def _free_slots():
    return Slot.query.filter_by(status="free").order_by(Slot.zone, Slot.code).all()


@bp.route("/entry", methods=["GET", "POST"])
@login_required
def entry():
    rates = Rate.query.order_by(Rate.vehicle_type).all()
    free_slots = _free_slots()
    form = request.form if request.method == "POST" else {}
    if request.method == "GET" and not free_slots:
        last = TurnAway.query.order_by(TurnAway.occurred_at.desc()).first()
        if last is None or (now_local() - last.occurred_at).total_seconds() > 60:
            db.session.add(TurnAway())
            db.session.commit()
    if request.method == "POST":
        plate = svc.normalize_plate(form.get("plate_number"))
        vtype = form.get("vehicle_type", "")
        errors = []
        perr = svc.validate_plate(plate)
        if perr:
            errors.append(perr)
        if not Rate.query.filter_by(vehicle_type=vtype).first():
            errors.append("Choose a vehicle type that has a rate.")
        try:
            slot = db.session.get(Slot, int(form.get("slot_id", "")))
        except (TypeError, ValueError):
            slot = None
        if slot is None or slot.status != "free":
            errors.append("That slot is not free. Please choose another.")
        if not perr:
            dup = ParkingSession.query.filter_by(plate_number=plate, status="active").first()
            if dup:
                errors.append(f"{plate} is already checked in (slot {dup.slot.code}).")
        if not errors:
            slot.status = "occupied"
            db.session.add(ParkingSession(plate_number=plate, vehicle_type=vtype, slot_id=slot.id,
                                          time_in=now_local(), logged_by=session["staff_id"]))
            audit("check_in", f"{plate} slot {slot.code}")
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("Another attendant just used that slot or plate. Please try again.")
            else:
                flash(f"{plate} checked in to slot {slot.code}.", "success")
                return redirect(url_for("main.dashboard"))
        for e in errors:
            flash(e, "error")
        free_slots = _free_slots()
    return render_template("entry.html", free_slots=free_slots, rates=rates, form=form)


@bp.route("/exit/<int:sid>", methods=["GET", "POST"])
@login_required
def exit_vehicle(sid):
    sess = db.get_or_404(ParkingSession, sid)
    if sess.status != "active":
        flash("This session is not active.", "error")
        return redirect(url_for("main.dashboard"))
    now = now_local()
    try:
        fee = svc.fee_for_session(sess, now)
    except svc.MissingRate:
        flash(f"No rate is configured for {sess.vehicle_type}. Ask the administrator.", "error")
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        sess.time_out, sess.fee, sess.status = now, fee, "closed"
        sess.slot.status = "free"
        audit("check_out", f"{sess.plate_number} fee {fee:.2f}")
        db.session.commit()
        flash(f"{sess.plate_number} checked out. Calculated fee: {fee:.2f} (collect payment separately).", "success")
        return redirect(url_for("main.dashboard"))
    return render_template("exit.html", ps=sess, fee_preview=fee, now=now)


@bp.route("/session/<int:sid>/plate", methods=["GET", "POST"])
@login_required
def edit_plate(sid):
    sess = db.get_or_404(ParkingSession, sid)
    if sess.status != "active":
        flash("Only a vehicle that is still parked can be corrected.", "error")
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        plate = svc.normalize_plate(request.form.get("plate_number"))
        err = svc.validate_plate(plate)
        if not err and plate != sess.plate_number and \
                ParkingSession.query.filter_by(plate_number=plate, status="active").first():
            err = f"{plate} is already checked in."
        if err:
            flash(err, "error")
        else:
            audit("plate_corrected", f"{sess.plate_number} -> {plate}")
            sess.plate_number = plate
            db.session.commit()
            flash("Plate number corrected.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("edit_plate.html", ps=sess)


@bp.route("/session/<int:sid>/void", methods=["POST"])
@admin_required
def void_session(sid):
    sess = db.get_or_404(ParkingSession, sid)
    reason = (request.form.get("reason") or "").strip()
    if sess.status == "voided":
        flash("Already voided.", "error")
    elif not (3 <= len(reason) <= 200):
        flash("Give a reason of 3 to 200 characters.", "error")
    else:
        if sess.status == "active":
            sess.slot.status = "free"
        sess.status, sess.voided_at = "voided", now_local()
        sess.voided_by, sess.void_reason = session["staff_id"], reason
        audit("void", f"session {sess.id} {sess.plate_number}: {reason}")
        db.session.commit()
        flash(f"Session {sess.id} voided and excluded from reports.", "success")
    return redirect(request.referrer or url_for("main.sessions"))


def _filtered_sessions():
    q = ParkingSession.query
    status = request.args.get("status", "all")
    plate = svc.normalize_plate(request.args.get("q"))
    day = request.args.get("date", "")
    if session.get("role") != "admin":  # attendants see today only
        day = now_local().strftime("%Y-%m-%d")
    if status in ("active", "closed", "voided"):
        q = q.filter_by(status=status)
    if plate:
        q = q.filter(ParkingSession.plate_number.contains(plate))
    if day:
        try:
            d0 = datetime.strptime(day, "%Y-%m-%d")
            q = q.filter(ParkingSession.time_in >= d0, ParkingSession.time_in < d0 + timedelta(days=1))
        except ValueError:
            flash("Date must look like 2026-11-09.", "error")
    return q.order_by(ParkingSession.time_in.desc()), status, plate, day


@bp.route("/sessions")
@login_required
def sessions():
    q, status, plate, day = _filtered_sessions()
    pager = q.paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    return render_template("sessions.html", pager=pager, status=status, plate=plate, day=day)


def _csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@bp.route("/sessions/export.csv")
@admin_required
def export_csv():
    q, *_ = _filtered_sessions()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "plate", "vehicle_type", "slot", "time_in", "time_out", "calculated_fee", "status"])
    for s in q.all():
        w.writerow([s.id, _csv_safe(s.plate_number), s.vehicle_type, s.slot.code,
                    s.time_in.strftime("%Y-%m-%d %H:%M"),
                    s.time_out.strftime("%Y-%m-%d %H:%M") if s.time_out else "",
                    "" if s.fee is None else f"{s.fee:.2f}", s.status])
    audit("export_csv")
    db.session.commit()
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sessions.csv"})


@bp.route("/slots", methods=["GET", "POST"])
@admin_required
def slots():
    if request.method == "POST":
        (code, zone), errors = svc.validate_slot(request.form.get("code"), request.form.get("zone"))
        if not errors and Slot.query.filter_by(code=code).first():
            errors.append("A slot with that code already exists.")
        for e in errors:
            flash(e, "error")
        if not errors:
            db.session.add(Slot(code=code, zone=zone, status="free"))
            audit("slot_added", f"{code} / {zone}")
            db.session.commit()
            flash(f"Slot {code} added.", "success")
        return redirect(url_for("main.slots"))
    return render_template("slots.html", slots=Slot.query.order_by(Slot.zone, Slot.code).all())


@bp.route("/slots/<int:sid>/toggle", methods=["POST"])
@admin_required
def toggle_slot(sid):
    slot = db.get_or_404(Slot, sid)
    if slot.status == "occupied":
        flash("An occupied slot cannot be blocked. Check the vehicle out first.", "error")
    else:
        slot.status = "free" if slot.status == "blocked" else "blocked"
        audit("slot_" + slot.status, slot.code)
        db.session.commit()
        flash(f"Slot {slot.code} is now {slot.status}.", "success")
    return redirect(url_for("main.slots"))


@bp.route("/rates", methods=["GET", "POST"])
@admin_required
def rates():
    if request.method == "POST":
        (vt, price, grace), errors = svc.validate_rate(request.form.get("vehicle_type"),
                                                       request.form.get("price_per_hour"),
                                                       request.form.get("grace_minutes"))
        for e in errors:
            flash(e, "error")
        if not errors:
            rate = Rate.query.filter_by(vehicle_type=vt).first()
            if rate:
                rate.price_per_hour, rate.grace_minutes = price, grace
            else:
                db.session.add(Rate(vehicle_type=vt, price_per_hour=price, grace_minutes=grace))
            audit("rate_saved", f"{vt} {price}/h grace {grace}")
            db.session.commit()
            flash(f"Rate for {vt} saved.", "success")
        return redirect(url_for("main.rates"))
    return render_template("rates.html", rates=Rate.query.order_by(Rate.vehicle_type).all())


@bp.route("/staff", methods=["GET", "POST"])
@admin_required
def staff():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "attendant")
        pw, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        errors = []
        if not svc.USERNAME_RE.match(username):
            errors.append("Username: 3 to 30 characters, lowercase letters, digits, dot, dash or underscore.")
        if not (2 <= len(name) <= 100):
            errors.append("Name must be 2 to 100 characters.")
        if role not in ("attendant", "admin"):
            errors.append("Role must be attendant or admin.")
        if Staff.query.filter_by(username=username).first():
            errors.append("That username is taken.")
        pe = svc.validate_password(pw, confirm)
        if pe:
            errors.append(pe)
        for e in errors:
            flash(e, "error")
        if not errors:
            s = Staff(name=name, username=username, role=role)
            s.set_password(pw)
            db.session.add(s)
            audit("staff_added", f"{username} ({role})")
            db.session.commit()
            flash(f"Account {username} created.", "success")
        return redirect(url_for("main.staff"))
    return render_template("staff.html", staff=Staff.query.order_by(Staff.username).all())


@bp.route("/staff/<int:sid>/toggle", methods=["POST"])
@admin_required
def toggle_staff(sid):
    s = db.get_or_404(Staff, sid)
    admins = Staff.query.filter_by(role="admin", active=True).count()
    if s.id == session["staff_id"]:
        flash("You cannot deactivate your own account.", "error")
    elif s.active and s.role == "admin" and admins <= 1:
        flash("At least one active administrator is required.", "error")
    else:
        s.active = not s.active
        audit("staff_active" if s.active else "staff_inactive", s.username)
        db.session.commit()
        flash(f"{s.username} is now {'active' if s.active else 'deactivated'}.", "success")
    return redirect(url_for("main.staff"))


@bp.route("/staff/<int:sid>/password", methods=["POST"])
@admin_required
def reset_staff_password(sid):
    s = db.get_or_404(Staff, sid)
    err = svc.validate_password(request.form.get("password", ""), request.form.get("confirm", ""))
    if err:
        flash(err, "error")
    else:
        s.set_password(request.form["password"])
        audit("password_reset", s.username)
        db.session.commit()
        flash(f"Password for {s.username} reset.", "success")
    return redirect(url_for("main.staff"))


@bp.route("/reports")
@admin_required
def reports():
    return render_template("reports.html", r=svc.build_reports())


@bp.route("/audit")
@admin_required
def audit_log():
    return render_template("audit.html", events=AuditEvent.query.order_by(AuditEvent.id.desc()).limit(200).all())


@bp.route("/api/occupancy")
@login_required
def api_occupancy():
    o = svc.occupancy_counts()
    return jsonify(total=o["total"], occupied=o["occupied"], free=o["free"], blocked=o["blocked"])
