"""Arama motorunun ve web arayuzunun paylastigi calisma-zamani durumu."""

state = {
    "running": False,
    "paused": False,
    "logs": [],
    "results": [],
    "current": None,
    "current_index": 0,   # kaldigi yer
    "total": 0,
}
