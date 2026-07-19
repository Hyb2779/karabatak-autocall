"""Aramalarin gercek yurutulme mantigi.
run_calls: Asterisk AMI uzerinden coklu SIP hesabi + eszamanli worker havuzu.
run_calls_cli: AMI baglanamazsa `asterisk -rx originate` ile tek hatli fallback."""
import subprocess
import threading
import time
import queue as _queue

from ami_client import AMIClient
from asterisk_config import get_trunk_names
from extensions import socketio
from logger import log
from settings_store import load_results, save_results
from state import state


def run_calls(settings, start_index=0):
    trunks = get_trunk_names(settings)

    probe = AMIClient()
    if not probe.connect():
        run_calls_cli(settings, start_index)
        return
    probe.disconnect()

    numbers_all = [n.strip() for n in settings["numbers"].splitlines() if n.strip()]
    total_all = len(numbers_all)
    state["total"] = total_all
    socketio.emit("total", {"total": total_all, "start_index": start_index})

    concurrency = max(1, int(settings.get("concurrency", len(trunks)) or len(trunks)))

    q = _queue.Queue()
    for idx in range(start_index, total_all):
        q.put((idx, numbers_all[idx]))

    results_lock = threading.Lock()
    ring_timeout = int(settings["ring_timeout"])
    wait_audio = int(settings["wait_before_audio"])
    delay = int(settings["delay"])

    def worker(trunk_name):
        ami = AMIClient()
        if not ami.connect():
            log(f"[{trunk_name}] AMI baglanamadi, worker durduruluyor.", "error")
            return
        while state["running"]:
            while state["paused"]:
                if not state["running"]:
                    ami.disconnect()
                    return
                time.sleep(0.5)
            try:
                idx, number = q.get_nowait()
            except _queue.Empty:
                break

            with results_lock:
                state["current"] = number
                state["current_index"] = idx
            socketio.emit("current", {"number": number, "index": idx})
            log(f"[{idx+1}/{total_all}] ({trunk_name}) Araniyor: {number}", "info")

            action_id = ami.originate(number, trunk_name, settings["sip_server"], ring_timeout)
            result_status = ami.wait_for_call_result(action_id, ring_timeout, wait_audio)

            result = {"number": number, "status": result_status, "time": time.strftime("%H:%M:%S"), "index": idx}

            if result_status in ("tamamlandı", "cevaplandı"):
                log(f"✓ {number}: {result_status}", "success")
            elif result_status == "meşgul":
                log(f"~ {number}: meşgul", "warn")
            elif result_status == "durduruldu":
                log(f"⏸ {number}: durduruldu", "warn")
                with results_lock:
                    state["results"].append(result)
                socketio.emit("result", result)
                break
            else:
                log(f"✗ {number}: {result_status}", "warn")

            with results_lock:
                state["results"].append(result)
                all_results = load_results()
                all_results.append(result)
                save_results(all_results)
            socketio.emit("result", result)

            if state["running"] and not state["paused"] and delay > 0:
                for _ in range(delay * 2):
                    if not state["running"] or state["paused"]:
                        break
                    time.sleep(0.5)

        ami.disconnect()

    threads = []
    for i in range(concurrency):
        trunk_name = trunks[i % len(trunks)]
        t = threading.Thread(target=worker, args=(trunk_name,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

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

        try:
            subprocess.run([
                "asterisk", "-rx",
                f"originate SIP/autocall_trunk/{number} application Playback autocall"
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
