"""Asterisk sip.conf dosyasinin panel ayarlarina gore otomatik yazilmasi
ve aktif SIP hesaplarina karsilik gelen trunk isimlerinin uretilmesi."""
import subprocess

from logger import log


def update_asterisk_sip(settings):
    server = settings.get("sip_server", "")
    if ":" in server:
        host, port = server.rsplit(":", 1)
    else:
        host, port = server, "5060"

    accounts = []
    u1, p1 = settings.get("sip_username", ""), settings.get("sip_password", "")
    if u1:
        accounts.append((u1, p1))
    u2, p2 = settings.get("sip_username2", ""), settings.get("sip_password2", "")
    if u2:
        accounts.append((u2, p2))

    lines = ["[general]", "defaultexpiry=3600", "context=default"]
    for username, password in accounts:
        lines.append(f"register => {username}:{password}@{host}:{port}/{username}")
    lines.append("")

    for username, password in accounts:
        trunk_name = f"autocall_trunk_{username}"
        lines += [
            f"[{trunk_name}]",
            "type=friend",
            f"host={host}",
            f"port={port}",
            f"username={username}",
            f"secret={password}",
            f"fromuser={username}",
            f"fromdomain={host}",
            "insecure=port,invite",
            "qualify=yes",
            "context=default",
            "",
        ]

    sip_conf = "\n".join(lines) + "\n"
    try:
        with open("/etc/asterisk/sip.conf", "w") as f:
            f.write(sip_conf)
        subprocess.run(["asterisk", "-rx", "sip reload"], capture_output=True)
        log(f"Asterisk SIP config güncellendi ({len(accounts)} hat).", "success")
    except Exception as e:
        log(f"Asterisk config güncellenemedi: {e}", "error")


def get_trunk_names(settings):
    """Aktif SIP hesaplarina karsilik gelen trunk isimlerini dondurur."""
    accounts = []
    u1 = settings.get("sip_username", "")
    if u1:
        accounts.append(f"autocall_trunk_{u1}")
    u2 = settings.get("sip_username2", "")
    if u2:
        accounts.append(f"autocall_trunk_{u2}")
    return accounts or ["autocall_trunk"]
