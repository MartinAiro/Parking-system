"""Parking Management System: application factory.

Run for development:   python run.py
Run for real use:      python serve.py        (production server)
"""
import click
from flask import Flask, render_template

from config import Config
from models import Rate, Slot, Staff, db


def init_db(demo_accounts=True):
    """Create tables and starter data (demo zones and rates are placeholders, not Maasai Mall's real layout)."""
    db.create_all()
    if demo_accounts and Staff.query.count() == 0:
        admin = Staff(name="System Admin", username="admin", role="admin")
        admin.set_password("admin123")
        att = Staff(name="Gate Attendant", username="attendant", role="attendant")
        att.set_password("attendant123")
        db.session.add_all([admin, att])
    if Rate.query.count() == 0:
        db.session.add_all([Rate(vehicle_type="Car", price_per_hour=100, grace_minutes=10),
                            Rate(vehicle_type="Motorbike", price_per_hour=50, grace_minutes=10),
                            Rate(vehicle_type="Truck", price_per_hour=200, grace_minutes=10),
                            Rate(vehicle_type="Visitor", price_per_hour=150, grace_minutes=5)])
    if Slot.query.count() == 0:
        # DEMO DATA ONLY: Maasai Mall's real layout has not been validated. Replace after authorised engagement.
        for prefix, zone in (("A", "Zone A (demo)"), ("B", "Zone B (demo)")):
            for i in range(1, 11):
                db.session.add(Slot(code=f"{prefix}-{i:02d}", zone=zone, status="free"))
    db.session.commit()


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    db.init_app(app)

    from routes import bp
    app.register_blueprint(bp)

    for code, title, msg in ((400, "Request not accepted", "Your form expired or was not valid. Go back, reload the page and try again."),
                             (404, "Page not found", "That page does not exist, or the record was not found."),
                             (429, "Too many attempts", "Please wait a few minutes and try again."),
                             (500, "Something went wrong", "The error has not changed any data. Please try again or tell the administrator.")):
        app.register_error_handler(code, lambda e, c=code, t=title, m=msg: (render_template("error.html", code=c, title=t, message=m), c))

    @app.cli.command("init-db")
    def _init_db():
        """Create tables and starter data."""
        init_db(app.config["SEED_DEMO_ACCOUNTS"])
        click.echo("Database ready.")

    @app.cli.command("seed-test-data")
    @click.option("--days", default=21, show_default=True)
    @click.option("--seed", default=42, show_default=True)
    @click.option("--reset", is_flag=True, help="Delete existing sessions first.")
    def _seed(days, seed, reset):
        """Fill the database with SYNTHETIC sessions for testing and demonstration."""
        import testdata
        init_db(app.config["SEED_DEMO_ACCOUNTS"])
        click.echo(testdata.generate(days=days, seed=seed, reset=reset))

    return app
