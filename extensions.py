"""
Flask app ve SocketIO nesneleri burada tek yerde olusturulur.
Diger tum moduller (routes, call_engine, vs.) bu dosyadan import eder.
Bu, app.py <-> routes.py <-> call_engine.py arasinda dongusel
import (circular import) sorununu onler.
"""
import os
from flask import Flask
from flask_socketio import SocketIO

from constants import UPLOAD_FOLDER

app = Flask(__name__)
app.secret_key = "autocall_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
