import sys
import os

BASE_DIR = "/var/www/ecochargeplus"
sys.path.insert(0, BASE_DIR)

# Optional but helpful
os.environ.setdefault("FLASK_ENV", "production")

from app import app as application  # expects: app.py has: app = Flask(__name__)
