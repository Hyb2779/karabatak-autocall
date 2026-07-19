"""Panel log akisi. state['logs']'a ekler ve socketio ile canli yayinlar."""
import time

from extensions import socketio
from state import state


def log(msg, level="info"):
    entry = {"msg": msg, "level": level, "time": time.strftime("%H:%M:%S")}
    state["logs"].append(entry)
    if len(state["logs"]) > 300:
        state["logs"] = state["logs"][-300:]
    socketio.emit("log", entry)
