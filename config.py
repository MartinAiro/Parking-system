"""Configuration. Everything sensitive comes from environment variables, not from the code."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _secret_key():
    """Use SECRET_KEY if set; otherwise create one once and keep it in instance/secret_key."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    INSTANCE_DIR.mkdir(exist_ok=True)
    f = INSTANCE_DIR / "secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


class Config:
    FACILITY_NAME = os.environ.get("FACILITY_NAME", "Maasai Mall, Ongata Rongai")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + str(INSTANCE_DIR / "parking.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = _secret_key()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 10  # one shift, in seconds
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_SECONDS = 300
    SEED_DEMO_ACCOUNTS = os.environ.get("SEED_DEMO_ACCOUNTS", "1") == "1"
    TESTING = False
