"""Asterisk Manager Interface (AMI) TCP istemcisi.
Arama baslatma (Originate) ve sonucunu (cevaplandi/mesgul/cevapsiz) bekleme."""
import socket
import threading
import time

from constants import AMI_HOST, AMI_PORT, AMI_USER, AMI_PASS
from logger import log
from state import state


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
            # AMI once event sonra response gonderiyor, birden fazla blok oku
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
            # Hata yoksa basarili say (event geldi ama response gec gelebilir)
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
        """Arama baslat, sonucu bekle"""
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
            self._read_response(timeout=3)
            return action_id

    def wait_for_call_result(self, action_id, ring_timeout, wait_audio):
        """Arama sonucunu bekle - cevaplandi/cevapsiz/mesgul"""
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
            buf = events[-1]  # Tamamlanmamis son event'i sakla

            for event_str in events[:-1]:
                if action_id not in event_str:
                    continue
                if "OriginateResponse" in event_str:
                    # Debug: tum event'i logla
                    for line in event_str.splitlines():
                        if any(k in line for k in ["Reason", "Response", "DialStatus", "ChannelState"]):
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
