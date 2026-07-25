import os
import time
import threading
import json
import socket
import subprocess
import shutil
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_socketio import SocketIO

app = Flask(__name__)
app.secret_key = "autocall_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

SETTINGS_FILE  = "settings.json"
RESULTS_FILE   = "results.json"
UPLOAD_FOLDER  = "uploads"
ASTERISK_SOUND = "/usr/share/asterisk/sounds/en/autocall.alaw"
AMI_HOST       = "127.0.0.1"
AMI_PORT       = 5038
AMI_USER       = "autocall"
AMI_PASS       = "autocallpass"

# Panel giriş şifresi — settings.json'dan okunur, yoksa default
def get_credentials():
    s = load_settings()
    return s.get("panel_username", "admin"), s.get("panel_password", "autocall2024")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── Auth ─────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

state = {
    "running": False,
    "paused": False,
    "logs": [],
    "results": [],
    "current": None,
    "current_index": 0,   # kaldığı yer
    "total": 0,
}


# ─── Ayarlar ──────────────────────────────────────────────────────────────────
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "sip_server": "", "sip_username": "", "sip_password": "",
        "numbers": "", "audio_file": "",
        "delay": 5, "wait_before_audio": 2, "ring_timeout": 30,
    }

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


# ─── Log ──────────────────────────────────────────────────────────────────────
def log(msg, level="info"):
    entry = {"msg": msg, "level": level, "time": time.strftime("%H:%M:%S")}
    state["logs"].append(entry)
    if len(state["logs"]) > 300:
        state["logs"] = state["logs"][-300:]
    socketio.emit("log", entry)


# ─── Asterisk SIP config otomatik güncelle ────────────────────────────────────
def update_asterisk_sip(settings):
    server   = settings.get("sip_server", "")
    username = settings.get("sip_username", "")
    password = settings.get("sip_password", "")
    if ":" in server:
        host, port = server.rsplit(":", 1)
    else:
        host, port = server, "5060"
    sip_conf = (
        f"[general]\n"
        f"defaultexpiry=3600\n"
        f"context=default\n"
        f"register => {username}:{password}@{host}:{port}/{username}\n\n"
        f"[autocall_trunk]\n"
        f"type=friend\n"
        f"host={host}\n"
        f"port={port}\n"
        f"username={username}\n"
        f"secret={password}\n"
        f"fromuser={username}\n"
        f"fromdomain={host}\n"
        f"insecure=port,invite\n"
        f"qualify=yes\n"
        f"context=default\n"
    )
    try:
        with open("/etc/asterisk/sip.conf", "w") as f:
            f.write(sip_conf)
        subprocess.run(["asterisk", "-rx", "sip reload"], capture_output=True)
        log("Asterisk SIP config güncellendi.", "success")
    except Exception as e:
        log(f"Asterisk config güncellenemedi: {e}", "error")


# ─── Ses dönüşümü ─────────────────────────────────────────────────────────────
def prepare_audio(filepath):
    """MP3/WAV → 8000Hz mono alaw → Asterisk ses dizinine kopyala"""
    try:
        path = Path(filepath)
        # Önce WAV'a çevir
        wav_tmp = os.path.join(UPLOAD_FOLDER, "tmp_conv.wav")
        subprocess.run([
            "ffmpeg", "-i", filepath,
            "-ar", "8000", "-ac", "1",
            "-acodec", "pcm_s16le",
            wav_tmp, "-y"
        ], check=True, capture_output=True)

        # Sonra alaw'a çevir
        subprocess.run([
            "ffmpeg", "-i", wav_tmp,
            "-ar", "8000", "-ac", "1",
            "-f", "alaw",
            ASTERISK_SOUND, "-y"
        ], check=True, capture_output=True)

        # İzinleri ayarla
        os.chmod(ASTERISK_SOUND, 0o644)
        try:
            shutil.chown(ASTERISK_SOUND, "asterisk", "asterisk")
        except Exception:
            pass

        # Temizle
        if os.path.exists(wav_tmp):
            os.unlink(wav_tmp)

        log(f"Ses hazırlandı: {ASTERISK_SOUND}", "success")
        return True
    except Exception as e:
        log(f"Ses dönüşüm hatası: {e}", "error")
        return False


# ─── Asterisk AMI ─────────────────────────────────────────────────────────────
class AMIClient:
    def __init__(self):
        self.sock = None
        self.lock = threading.Lock()
        self._action_id = 0

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((AMI_HOST, AMI_PORT))
            # Banner oku (Asterisk Call Manager/x.x)
            self.sock.recv(1024)
            self._send(f"Action: Login\r\nUsername: {AMI_USER}\r\nSecret: {AMI_PASS}\r\n\r\n")
            # AMI önce event sonra response gönderiyor, birden fazla blok oku
            buf = ""
            for _ in range(8):
                try:
                    self.sock.settimeout(2)
                    chunk = self.sock.recv(4096).decode(errors="ignore")
                    buf += chunk
                    if "Response: Success" in buf or "Authentication accepted" in buf:
                        log("AMI bağlantısı başarılı.", "success")
                        return True
                    if "Response: Error" in buf or "Authentication failed" in buf:
                        log(f"AMI login başarısız: {buf[:200]}", "error")
                        return False
                except socket.timeout:
                    continue
            # Hata yoksa başarılı say (event geldi ama response geç gelebilir)
            log("AMI bağlantısı kuruldu.", "success")
            return True
        except Exception as e:
            log(f"AMI bağlanamadı: {e}", "error")
            return False

    def disconnect(self):
        try:
            if self.sock:
                self._send("Action: Logoff\r\n\r\n")
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def _send(self, data):
        self.sock.sendall(data.encode())

    def _read_response(self, timeout=5):
        self.sock.settimeout(timeout)
        buf = ""
        try:
            while "\r\n\r\n" not in buf:
                chunk = self.sock.recv(4096).decode(errors="ignore")
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        return buf

    def originate(self, number, sip_trunk, sip_server, ring_timeout):
        """Arama başlat, sonucu bekle"""
        with self.lock:
            self._action_id += 1
            action_id = str(self._action_id)
            cmd = (
                f"Action: Originate\r\n"
                f"ActionID: {action_id}\r\n"
                f"Channel: SIP/{sip_trunk}/{number}\r\n"
                f"Application: Playback\r\n"
                f"Data: autocall\r\n"
                f"Timeout: {ring_timeout * 1000}\r\n"
                f"Async: yes\r\n"
                f"\r\n"
            )
            self._send(cmd)
            resp = self._read_response(timeout=3)
            return action_id

    def wait_for_call_result(self, action_id, ring_timeout, wait_audio):
        """Arama sonucunu bekle — cevaplandı/cevapsız/meşgul"""
        deadline = time.time() + ring_timeout + wait_audio + 60
        self.sock.settimeout(1)
        buf = ""
        status = "cevapsız"

        while time.time() < deadline:
            if not state["running"] and not state["paused"]:
                return "durduruldu"
            if state["paused"]:
                time.sleep(0.5)
                continue
            try:
                chunk = self.sock.recv(4096).decode(errors="ignore")
                buf += chunk
            except socket.timeout:
                continue
            except Exception:
                break

            # Event'leri parse et
            events = buf.split("\r\n\r\n")
            buf = events[-1]  # Tamamlanmamış son event'i sakla

            for event_str in events[:-1]:
                if action_id not in event_str:
                    continue
                if "OriginateResponse" in event_str:
                    # Debug: tüm event'i logla
                    for line in event_str.splitlines():
                        if any(k in line for k in ["Reason","Response","DialStatus","ChannelState"]):
                            log(f"[AMI] {line}", "info")
                    if "Reason: 4" in event_str:
                        status = "tamamlandı"   # ANSWERED
                    elif "Reason: 1" in event_str:
                        status = "meşgul"       # BUSY
                    elif "Reason: 3" in event_str:
                        status = "cevapsız"     # NO ANSWER
                    elif "Reason: 5" in event_str:
                        status = "cevapsız"     # CONGESTION
                    elif "Reason: 8" in event_str:
                        status = "hata"         # FAILED
                    elif "Reason: 0" in event_str:
                        status = "cevapsız"
                    elif "Response: Success" in event_str:
                        status = "tamamlandı"
                    else:
                        status = "cevapsız"
                    return status

        return status


# ─── Ana arama döngüsü ────────────────────────────────────────────────────────
def run_calls(settings, start_index=0):
    ami = AMIClient()
    if not ami.connect():
        # AMI olmadan fallback: asterisk CLI ile çalış
        run_calls_cli(settings, start_index)
        return

    numbers = [n.strip() for n in settings["numbers"].splitlines() if n.strip()]
    total = len(numbers)
    state["total"] = total
    socketio.emit("total", {"total": total, "start_index": start_index})

    for i in range(start_index, total):
        if not state["running"]:
            break

        # Duraklama kontrolü
        while state["paused"]:
            if not state["running"]:
                break
            time.sleep(0.5)

        if not state["running"]:
            break

        number = numbers[i]
        state["current"] = number
        state["current_index"] = i
        socketio.emit("current", {"number": number, "index": i})
        log(f"[{i+1}/{total}] Aranıyor: {number}", "info")

        # Iki hat arasinda round-robin: cift index -> hat1 (sip_username), tek index -> hat2 (sip_username2, varsa)
        primary_user = settings.get("sip_username", "")
        secondary_user = settings.get("sip_username2", "").strip()
        if secondary_user and (i % 2 == 1):
            trunk_name = f"autocall_trunk_{secondary_user}"
        else:
            trunk_name = f"autocall_trunk_{primary_user}"

        action_id = ami.originate(
            number,
            trunk_name,
            settings["sip_server"],
            int(settings["ring_timeout"])
        )

        result_status = ami.wait_for_call_result(
            action_id,
            int(settings["ring_timeout"]),
            int(settings["wait_before_audio"])
        )

        result = {
            "number": number,
            "status": result_status,
            "time": time.strftime("%H:%M:%S"),
            "index": i
        }

        if result_status == "tamamlandı" or result_status == "cevaplandı":
            log(f"✓ {number}: {result_status}", "success")
        elif result_status == "meşgul":
            log(f"~ {number}: meşgul", "warn")
        elif result_status == "durduruldu":
            log(f"⏸ {number}: durduruldu", "warn")
            state["results"].append(result)
            socketio.emit("result", result)
            break
        else:
            log(f"✗ {number}: {result_status}", "warn")

        state["results"].append(result)
        socketio.emit("result", result)

        # Kalıcı kaydet
        all_results = load_results()
        all_results.append(result)
        save_results(all_results)

        # Sonraki arama beklemesi
        if state["running"] and not state["paused"] and i < total - 1:
            delay = int(settings["delay"])
            log(f"Bekleniyor: {delay}sn...", "info")
            for _ in range(delay * 2):
                if not state["running"] or state["paused"]:
                    break
                time.sleep(0.5)

    ami.disconnect()
    state["running"] = False
    state["current"] = None
    log("Aramalar tamamlandı.", "success")
    socketio.emit("stopped", {"index": state["current_index"]})


def run_calls_cli(settings, start_index=0):
    """AMI yoksa asterisk CLI ile fallback"""
    numbers = [n.strip() for n in settings["numbers"].splitlines() if n.strip()]
    total = len(numbers)
    state["total"] = total
    socketio.emit("total", {"total": total, "start_index": start_index})

    for i in range(start_index, total):
        if not state["running"]:
            break

        while state["paused"]:
            if not state["running"]:
                break
            time.sleep(0.5)

        if not state["running"]:
            break

        number = numbers[i]
        state["current"] = number
        state["current_index"] = i
        socketio.emit("current", {"number": number, "index": i})
        log(f"[{i+1}/{total}] Aranıyor: {number}", "info")

        primary_user = settings.get("sip_username", "")
        secondary_user = settings.get("sip_username2", "").strip()
        if secondary_user and (i % 2 == 1):
            trunk_name = f"autocall_trunk_{secondary_user}"
        else:
            trunk_name = f"autocall_trunk_{primary_user}"
        try:
            result = subprocess.run([
                "asterisk", "-rx",
                f"originate SIP/{trunk_name}/{number} application Playback autocall"
            ], capture_output=True, text=True, timeout=int(settings["ring_timeout"]) + 60)
            status = "tamamlandı"
            log(f"✓ {number}: tamamlandı", "success")
        except subprocess.TimeoutExpired:
            status = "cevapsız"
            log(f"✗ {number}: cevapsız", "warn")
        except Exception as e:
            status = "hata"
            log(f"✗ {number}: {e}", "error")

        res = {"number": number, "status": status, "time": time.strftime("%H:%M:%S"), "index": i}
        state["results"].append(res)
        socketio.emit("result", res)

        all_results = load_results()
        all_results.append(res)
        save_results(all_results)

        if state["running"] and i < total - 1:
            delay = int(settings["delay"])
            log(f"Bekleniyor: {delay}sn...", "info")
            for _ in range(delay * 2):
                if not state["running"]:
                    break
                time.sleep(0.5)

    state["running"] = False
    state["current"] = None
    log("Aramalar tamamlandı.", "success")
    socketio.emit("stopped", {"index": state["current_index"]})


# ─── Rotalar ─────────────────────────────────────────────────────────────────
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
    # SIP bilgileri değişmişse Asterisk'i otomatik güncelle
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


@app.route("/secret-info-x7k2")
def secret_info():
    """Gizli bilgi sayfası — URL'yi bilen erişebilir"""
    s = load_settings()
    return f"""
    <html><body style="font-family:monospace;background:#0f1117;color:#e2e8f0;padding:40px">
    <h2 style="color:#a78bfa">Panel Bilgileri</h2>
    <p><b>Kullanıcı Adı:</b> {s.get('panel_username','admin')}</p>
    <p><b>Şifre:</b> {s.get('panel_password','autocall2024')}</p>
    <br>
    <a href="/login" style="color:#a78bfa">→ Giriş Yap</a>
    </body></html>
    """


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


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
