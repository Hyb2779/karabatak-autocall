"""Panel giris/kimlik dogrulama yardimcilari."""
from functools import wraps

from flask import redirect, session, url_for

from settings_store import load_settings


def get_credentials():
    """Panel giris kullanici adi/sifresi - settings.json'dan okunur, yoksa default."""
    s = load_settings()
    return s.get("panel_username", "admin"), s.get("panel_password", "autocall2024")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated
