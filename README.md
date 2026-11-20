# ParkFlow: Parking Management System (prototype)

A web-based system for recording vehicle entry and exit, allocating parking slots, calculating
parking fees from recorded duration, and reporting on parking activity. Built for the Information
Systems Project proposal *Web-Based Parking Management System for Maasai Mall, Ongata Rongai*
(Africa International University, SCET).

## Honest status
- This is a **prototype developed with test data**. It has **not been validated with Maasai Mall**,
  and nothing here is a Maasai Mall record. Demo zones, slots and rates are **placeholders**.
- The generative-AI assistant Claude (Anthropic) helped write the code, the tests and the
  diagrams (declared in the proposal). The student is expected to be able to explain and
  re-run all of it.
- The system **calculates** a fee owed. It does **not** process or confirm payment, and slot status
  is **recorded by attendants**, never sensed by hardware.

## Quick start (Windows, Mac or Linux; Python 3.10+)
```bash
python -m venv venv
venv\Scripts\activate            # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
python run.py                    # open http://127.0.0.1:5000
```
Demo logins (the system warns until they are changed): `admin / admin123`, `attendant / attendant123`.
**Change both passwords first** (click your name, top right) or create real accounts under *Staff*.

## Test data (synthetic, clearly labelled)
```bash
python -m flask --app app seed-test-data --days 21 --seed 42 --reset
```
Creates about three weeks of invented sessions (all plates start with `TST`), with lunchtime/evening peaks,
repeat vehicles, voids and facility-full events, and turns on a "TEST DATA" banner. A ready-made copy is in
`evidence/parking_testdata.db` (set `DATABASE_URL=sqlite:///<path>` to use it).

## Tests
```bash
python -m pytest                                  # 67 automated tests
python -m pytest --cov=. --cov-report=term        # with coverage
```

## Running it for real use (after permission and validation)
```bash
set SECRET_KEY=<long random text>      # Mac/Linux: export
set SEED_DEMO_ACCOUNTS=0               # no demo accounts on a live system (create staff first with
                                       #   a one-time run using SEED_DEMO_ACCOUNTS=1, then change passwords)
python serve.py                        # Waitress production server on port 8000
python backup.py                       # daily database backup
```
Use a UPS and keep backups off the computer. Serve over HTTPS if it is reachable beyond the mall's own
network (set `SESSION_COOKIE_SECURE=1`).

## Where things are
| File | Purpose |
|---|---|
| `app.py` | application factory, starter data, command-line commands |
| `routes.py` | web pages and actions (one section each), access control, CSRF, login lockout |
| `services.py` | fee calculation, validation, report queries |
| `models.py` | database tables (staff, rates, slots, sessions, audit log, turn-aways) |
| `testdata.py` | synthetic test-data generator |
| `config.py` | settings from environment variables |
| `templates/`, `static/` | pages and styling |
| `tests/` | automated tests (IDs T01-T51) |
| `run.py`, `serve.py`, `backup.py` | development server, production server, backup |

## Configuration (environment variables)
`SECRET_KEY`, `DATABASE_URL`, `FACILITY_NAME`, `SEED_DEMO_ACCOUNTS`, `SESSION_COOKIE_SECURE`, `HOST`, `PORT`, `FLASK_DEBUG`.

## Known limitations
No hardware sensors, no payment processing, no number-plate recognition. SQLite suits a single gate;
use PostgreSQL or MySQL if several terminals must share data. Login throttling is per process and resets on
restart. Not tested with many simultaneous users or on Windows by the author of the code.
