"""Development server (debug off by default; set FLASK_DEBUG=1 to turn it on)."""
import os
from app import create_app, init_db

app = create_app()
with app.app_context():
    init_db(app.config["SEED_DEMO_ACCOUNTS"])

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
