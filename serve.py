"""Production server (Waitress). Put it behind the mall's network; set SECRET_KEY and change demo passwords first."""
import os
from waitress import serve
from run import app

if __name__ == "__main__":
    serve(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8000)), threads=4)
