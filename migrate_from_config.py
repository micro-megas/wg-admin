"""
Скрипт миграции: читает существующий конфиг WireGuard и заполняет БД.

Использование:
    python migrate_from_config.py [--config /etc/wireguard/wg0.conf] [--dry-run]

--dry-run — показать что будет импортировано, ничего не записывая в БД.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, init_db
from app.models import Peer, ServerKey, TrafficStat
from app.wireguard import parse_wg_show


def parse_wg_config(config_path: str) -> dict:
    """
    Разобрать серверный конфиг WireGuard.

    Возвращает:
    {
        "interface": {
            "private_key": "...",
            "address": "...",
            "listen_port": ...,
        },
        "peers": [
            {
                "public_key": "...",
                "preshared_key": "..." | None,
                "allowed_ips": "10.10.0.2/32",
                "comment": "..." | None,   # если есть # comment в конфиге
            },
            ...
        ]
    }
    """
    content = Path(config_path).read_text()

    result = {"interface": {}, "peers": []}
    current_section = None
    current_peer = None

    for line in content.splitlines():
        stripped = line.strip()

        # Пропуск пустых строк
        if not stripped:
            continue

        # Комментарии-заголовки секций
        if stripped.startswith("[Interface]"):
            current_section = "interface"
            continue
        elif stripped.startswith("[Peer]"):
            current_section = "peer"
            if current_peer:
                result["peers"].append(current_peer)
            current_peer = {}
            continue

        # Обычный комментарий — может быть именем пира
        if stripped.startswith("#") and current_section == "peer" and current_peer is not None:
            comment = stripped.lstrip("#").strip()
            if "comment" not in current_peer:
                current_peer["comment"] = comment
            continue

        # Парсинг ключ = значение
        if "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()

        if current_section == "interface":
            if key == "PrivateKey":
                result["interface"]["private_key"] = value
            elif key == "Address":
                result["interface"]["address"] = value
            elif key == "ListenPort":
                result["interface"]["listen_port"] = int(value)

        elif current_section == "peer" and current_peer is not None:
            if key == "PublicKey":
                current_peer["public_key"] = value
            elif key == "PresharedKey":
                current_peer["preshared_key"] = value
            elif key == "AllowedIPs":
                # Берём первый IP (обычно /32)
                current_peer["allowed_ips"] = value
            elif key == "Endpoint":
                current_peer["endpoint"] = value

    # Последний пир
    if current_peer:
        result["peers"].append(current_peer)

    return result


def extract_ip(allowed_ips: str) -> str:
    """Извлечь IP-адрес из AllowedIPs (берём первый)."""
    first = allowed_ips.split(",")[0].strip()
    # Убираем маску
    ip = first.split("/")[0]
    return ip


async def migrate(config_path: str, dry_run: bool = False):
    print(f"Чтение конфига: {config_path}")

    if not Path(config_path).exists():
        print(f"ОШИБКА: файл {config_path} не найден")
        sys.exit(1)

    config = parse_wg_config(config_path)

    iface = config["interface"]
    peers = config["peers"]

    print(f"\n=== Интерфейс ===")
    print(f"  ListenPort: {iface.get('listen_port', '?')}")
    print(f"  Address:    {iface.get('address', '?')}")
    print(f"  PrivKey:    {iface.get('private_key', '?')[:12]}...")

    print(f"\n=== Пиры ({len(peers)}) ===")
    for p in peers:
        ip = extract_ip(p.get("allowed_ips", ""))
        name = p.get("comment", "(без имени)")
        psk = "есть" if p.get("preshared_key") else "нет"
        print(f"  {ip:15s}  {name:20s}  PSK: {psk}  Key: {p.get('public_key', '?')[:12]}...")

    if dry_run:
        print("\n--dry-run: запись в БД пропущена")
        return

    # Получить текущую статистику из wg show
    print("\nСбор статистики из wg show...")
    raw_stats = parse_wg_show()

    # Инициализировать БД (создать таблицы если нет)
    await init_db()

    async with async_session() as db: #AsyncSession:
        # --- Сохранить ключ сервера ---
        server_priv = iface.get("private_key")
        if not server_priv:
            print("ОШИБКА: приватный ключ сервера не найден в конфиге")
            sys.exit(1)

        # Вычислить публичный ключ сервера
        from app.wireguard import _run
        erver_pub = _run(["wg", "pubkey"], input_data=server_priv) if server_priv else ""

        # Проверить, есть ли уже запись
        existing_key = await db.execute(
            select(ServerKey).where(ServerKey.interface == "wg0")
        )
        existing_key = existing_key.scalars().first()

        if existing_key:
            existing_key.private_key = server_priv
            existing_key.public_key = server_pub
            print(f"\nОбновлён ключ сервера (публичный: {server_pub[:12]}...)")
        else:
            db.add(ServerKey(
                interface="wg0",
                private_key=server_priv,
                public_key=server_pub,
            ))
            print(f"\nСоздан ключ сервера (публичный: {server_pub[:12]}...)")

        # --- Импорт пиров ---
        imported = 0
        skipped = 0

        for p in peers:
            pub_key = p.get("public_key")
            if not pub_key:
                print("  ПРОПУСК: пир без публичного ключа")
                skipped += 1
                continue

            assigned_ip = extract_ip(p.get("allowed_ips", ""))
            if not assigned_ip:
                print(f"  ПРОПУСК: нет IP у пира {pub_key[:12]}...")
                skipped += 1
                continue

            # Проверить, нет ли уже такого пира в БД
            existing = await db.execute(
                select(Peer).where(Peer.public_key == pub_key)
            )
            existing = existing.scalars().first()

            if existing:
                print(f"  ПРОПУСК: пир {assigned_ip} уже в БД")
                skipped += 1
                continue

            name = p.get("comment") or f"Peer-{assigned_ip}"
            psk = p.get("preshared_key")

            # Статистика из wg show
            stats = raw_stats.get(pub_key, {})
            rx = stats.get("rx", 0)
            tx = stats.get("tx", 0)
            handshake_str = stats.get("last_handshake")

            peer = Peer(
                name=name,
                public_key=pub_key,
                private_key="",           # нет в серверном конфиге
                preshared_key=psk,
                assigned_ip=assigned_ip,
                is_active=True,
                speed_limit_mbps=0,
                data_quota_bytes=0,
            )
            db.add(peer)
            await db.flush()

            # Записать начальную статистику, если есть
            if rx > 0 or tx > 0:
                stat = TrafficStat(
                    peer_id=peer.id,
                    rx_bytes=rx,
                    tx_bytes=tx,
                )
                db.add(stat)

            imported += 1
            print(f"  ИМПОРТ: {assigned_ip:15s}  {name:20s}  rx={rx} tx={tx}")

        await db.commit()

        print(f"\n=== Итог ===")
        print(f"  Импортировано: {imported}")
        print(f"  Пропущено:     {skipped}")
        print(f"  Всего в конфиге: {len(peers)}")
        print(f"\nГотово! БД заполнена.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Миграция конфига WireGuard в БД")
    parser.add_argument(
        "--config",
        default="/etc/wireguard/wg0.conf",
        help="Путь к конфигу WireGuard (по умолчанию /etc/wireguard/wg0.conf)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, что будет импортировано, без записи в БД",
    )
    args = parser.parse_args()

    asyncio.run(migrate(args.config, args.dry_run))
