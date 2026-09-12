import subprocess
import ipaddress
from app.config import settings


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def generate_keypair() -> tuple[str, str]:
    """Возвращает (private_key, public_key)."""
    private = _run(["wg", "genkey"])
    public = _run(["wg", "pubkey"], input=private)
    return private, public


def generate_preshared_key() -> str:
    return _run(["wg", "genpsk"])


def get_server_keypair() -> tuple[str, str]:
    """Сгенерировать ключ серверного интерфейса."""
    return generate_keypair()


def get_next_ip(used_ips: set[str]) -> str:
    """Найти следующий свободный IP в подсети."""
    network = ipaddress.ip_network(settings.wg_network, strict=False)
    for ip in network.hosts():
        ip_str = str(ip)
        if ip_str not in used_ips:
            return ip_str
    raise RuntimeError("No free IPs in the pool")


def build_server_config(
    server_private_key: str,
    server_port: int,
    peers: list[dict],
) -> str:
    """
    Собрать конфиг сервера /etc/wireguard/wg0.conf.
    peers — список словарей: public_key, preshared_key, assigned_ip, is_active
    """
    lines = [
        "[Interface]",
        f"PrivateKey = {server_private_key}",
        f"Address = {settings.wg_network.split('/')[0].rsplit('.', 1)[0]}.1/24",
        f"ListenPort = {server_port}",
        "PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE",
        "PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE",
        "",
    ]
    for p in peers:
        if not p["is_active"]:
            continue
        lines.extend([
            "[Peer]",
            f"PublicKey = {p['public_key']}",
        ])
        if p.get("preshared_key"):
            lines.append(f"PresharedKey = {p['preshared_key']}")
        lines.append(f"AllowedIPs = {p['assigned_ip']}/32")
        lines.append("")
    return "\n".join(lines)


def build_client_config(
    client_private_key: str,
    client_assigned_ip: str,
    server_public_key: str,
    server_endpoint: str,
    preshared_key: str | None = None,
) -> str:
    """Собрать конфиг для клиента."""
    lines = [
        "[Interface]",
        f"PrivateKey = {client_private_key}",
        f"Address = {client_assigned_ip}/32",
        f"DNS = {settings.wg_dns}",
        "",
        "[Peer]",
        f"PublicKey = {server_public_key}",
        f"Endpoint = {server_endpoint}:{settings.wg_port}",
        "AllowedIPs = 0.0.0.0/0",
        "PersistentKeepalive = 25",
    ]
    if preshared_key:
        lines.insert(2, f"PresharedKey = {preshared_key}")
    return "\n".join(lines)


def apply_config(config_text: str, interface: str = settings.wg_interface):
    """Перезаписать конфиг и перезапустить интерфейс."""
    conf_path = f"/etc/wireguard/{interface}.conf"
    with open(conf_path, "w") as f:
        f.write(config_text)
    _run(["wg-quick", "down", interface])
    _run(["wg-quick", "up", interface])


def parse_wg_show(interface: str = settings.wg_interface) -> dict:
    """
    Распарсить `wg show <iface` и вернуть словарь:
    { public_key: { rx, tx, last_handshake } }
    """
    try:
        output = _run(["wg", "show", interface])
    except subprocess.CalledProcessError:
        return {}

    result = {}
    current_key = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("peer:"):
            current_key = line.split(":", 1)[1].strip()
            result[current_key] = {"rx": 0, "tx": 0, "last_handshake": None}
        elif current_key:
            if line.startswith("transfer:"):
                # transfer: 12.3 MiB received, 5.1 MiB sent
                parts = line.split("transfer:")[1].strip()
                # Упрощённый парсинг
                recv_part, sent_part = parts.split(",")
                rx = _parse_size(recv_part.strip())
                tx = _parse_size(sent_part.strip())
                result[current_key]["rx"] = rx
                result[current_key]["tx"] = tx
            elif line.startswith("latest handshake:"):
                # Просто сохраняем как строку, можно парсить в datetime
                result[current_key]["last_handshake"] = line.split(":", 1)[1].strip()
    return result


def _parse_size(s: str) -> int:
    """Парсить '12.3 MiB' -> байты."""
    s = s.replace("received", "").replace("sent", "").strip()
    try:
        num, unit = s.split()
        num = float(num)
        multipliers = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
        return int(num * multipliers.get(unit, 1))
    except (ValueError, KeyError):
        return 0
