"""Panelin tum HTTP route'lari."""
import os
import threading

from flask import redirect, render_template, request, jsonify, url_for, session

from asterisk_config import update_asterisk_sip
from audio import prepare_audio
from auth import get_credentials, login_required
from call_engine import run_calls
from constants import ASTERISK_SOUND, UPLOAD_FOLDER
from extensions import app, socketio
from logger import log
from settings_store import load_results, load_settings, save_results, save_settings
from state import state


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username, password = get_credentials()
        if (request.form.get("username") == username and
                request.form.get("password") == password):
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Kullanıcı adı veya şifre hatalı."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    settings = load_settings()
    all_results = load_results()
    return render_template("index.html", settings=settings, state=state, all_results=all_results)


@app.route("/save", methods=["POST"])
@login_required
def save():
    settings = load_settings()
    settings["sip_server"]        = request.form.get("sip_server", "")
    settings["sip_username"]      = request.form.get("sip_username", "")
    settings["sip_password"]      = request.form.get("sip_password", "")
    settings["sip_username2"]     = request.form.get("sip_username2", "")
    settings["sip_password2"]     = request.form.get("sip_password2", "")
    settings["concurrency"]       = int(request.form.get("concurrency", 2) or 2)
    settings["numbers"]           = request.form.get("numbers", "")
    settings["delay"]             = int(request.form.get("delay", 5))
    settings["wait_before_audio"] = int(request.form.get("wait_before_audio", 2))
    settings["ring_timeout"]      = int(request.form.get("ring_timeout", 30))

    if "audio_file" in request.files:
        f = request.files["audio_file"]
        if f.filename:
            save_path = os.path.join(UPLOAD_FOLDER, f.filename)
            f.save(save_path)
            settings["audio_file"] = save_path
            threading.Thread(target=prepare_audio, args=(save_path,), daemon=True).start()

    save_settings(settings)
    # SIP bilgileri degismisse Asterisk'i otomatik guncelle
    threading.Thread(target=update_asterisk_sip, args=(settings,), daemon=True).start()
    return redirect(url_for("index"))


@app.route("/start", methods=["POST"])
@login_required
def start():
    if state["running"]:
        return jsonify({"ok": False, "msg": "Zaten çalışıyor"})
    settings = load_settings()
    if not settings["sip_server"] or not settings["sip_username"]:
        return jsonify({"ok": False, "msg": "SIP ayarları eksik"})
    if not settings["numbers"].strip():
        return jsonify({"ok": False, "msg": "Numara listesi boş"})
    if not settings["audio_file"] or not os.path.exists(settings["audio_file"]):
        return jsonify({"ok": False, "msg": "Ses dosyası bulunamadı"})
    if not os.path.exists(ASTERISK_SOUND):
        if not prepare_audio(settings["audio_file"]):
            return jsonify({"ok": False, "msg": "Ses dönüşümü başarısız"})

    resume_index = request.json.get("resume_index", 0) if request.is_json else 0
    start_index = int(request.form.get("resume_index", resume_index))

    state["running"] = True
    state["paused"] = False
    state["logs"] = []
    state["results"] = []
    state["current"] = None

    t = threading.Thread(target=run_calls, args=(settings, start_index), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/pause", methods=["POST"])
@login_required
def pause():
    if not state["running"]:
        return jsonify({"ok": False, "msg": "Çalışmıyor"})
    state["paused"] = not state["paused"]
    log(f"{'⏸ Duraklatıldı' if state['paused'] else '▶ Devam ediyor'}", "warn" if state["paused"] else "success")
    socketio.emit("paused", {"paused": state["paused"], "index": state["current_index"]})
    return jsonify({"ok": True, "paused": state["paused"], "index": state["current_index"]})


@app.route("/stop", methods=["POST"])
@login_required
def stop():
    state["running"] = False
    state["paused"] = False
    return jsonify({"ok": True, "index": state["current_index"]})


@app.route("/status")
@login_required
def status():
    return jsonify({
        "running": state["running"],
        "paused": state["paused"],
        "current": state["current"],
        "current_index": state["current_index"],
        "total": state["total"],
        "results": state["results"],
        "logs": state["logs"][-50:],
    })


@app.route("/clear_results", methods=["POST"])
@login_required
def clear_results():
    save_results([])
    return jsonify({"ok": True})


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    success = None
    if request.method == "POST":
        current_user, current_pass = get_credentials()
        old_password    = request.form.get("old_password", "")
        new_username    = request.form.get("new_username", "").strip()
        new_password    = request.form.get("new_password", "")
        new_password2   = request.form.get("new_password2", "")

        if old_password != current_pass:
            error = "Mevcut şifre hatalı."
        elif not new_username:
            error = "Kullanıcı adı boş olamaz."
        elif len(new_password) < 6:
            error = "Yeni şifre en az 6 karakter olmalı."
        elif new_password != new_password2:
            error = "Yeni şifreler eşleşmiyor."
        else:
            settings = load_settings()
            settings["panel_username"] = new_username
            settings["panel_password"] = new_password
            save_settings(settings)
            success = "Giriş bilgileri güncellendi."

    current_user, _ = get_credentials()
    return render_template("change_password.html", error=error, success=success, current_user=current_user)
