import subprocess
from app.config import settings

IFACE = settings.wg_interface


def _run(cmd: list[str]):
    subprocess.run(cmd, capture_output=True, text=True, check=False)


def init_shaper():
    """Инициализировать корневой HTB-qdisc."""
    _run(["tc", "qdisc", "del", "dev", IFACE, "root"])  # сброс старых правил
    _run(["tc", "qdisc", "add", "dev", IFACE, "root", "handle", "1:", "htb", "default", "9999"])
    _run(["tc", "class", "add", "dev", IFACE, "parent", "1:", "classid", "1:1", "htb", "rate", "1000mbit"])


def apply_limit(peer_ip: str, speed_mbps: int):
    """
    Применить лимит скорости для пира.
    classid вычисляется из последнего октета IP.
    """
    last_octet = int(peer_ip.split(".")[-1])
    class_id = f"1:{last_octet}"
    rate = f"{speed_mbps}mbit" if speed_mbps > 0 else "1000mbit"

    # Удалить старый класс (если есть) — тихо игнорируем ошибку
    _run(["tc", "class", "del", "dev", IFACE, "parent", "1:", "classid", class_id])

    # Создать класс с лимитом
    _run(["tc", "class", "add", "dev", IFACE, "parent", "1:1", "classid", class_id, "htb", "rate", rate, "ceil", rate])

    # Фильтры: исходящий (src) и входящий (dst)
    _run(["tc", "filter", "add", "dev", IFACE, "protocol", "ip", "parent", "1:", "prio", "1", "u32", "match", "ip", "src", peer_ip, "flowid", class_id])
    _run(["tc", "filter", "add", "dev", IFACE, "protocol", "ip", "parent", "1:", "prio", "1", "u32", "match", "ip", "dst", peer_ip, "flowid", class_id])


def remove_limit(peer_ip: str):
    """Удалить лимит для пира."""
    last_octet = int(peer_ip.split(".")[-1])
    class_id = f"1:{last_octet}"
    _run(["tc", "class", "del", "dev", IFACE, "parent", "1:", "classid", class_id])
