"""Panel ayarlarinin (settings.json) ve arama sonuclarinin (results.json)
diske okunmasi/yazilmasi."""
import json
import os

from constants import SETTINGS_FILE, RESULTS_FILE


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "sip_server": "", "sip_username": "", "sip_password": "",
        "sip_username2": "", "sip_password2": "", "concurrency": 2,
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
