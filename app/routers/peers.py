from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Peer, ServerKey
from app.schemas import PeerCreate, PeerUpdate, PeerResponse, PeerConfig
from app.wireguard import (
    generate_keypair, generate_preshared_key, get_next_ip,
    build_server_config, build_client_config, apply_config,
)
from app.traffic import init_shaper, apply_limit, remove_limit
from app.config import settings

router = APIRouter(prefix="/api/peers", tags=["peers"])


@router.get("", response_model=list[PeerResponse])
async def list_peers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Peer).order_by(Peer.created_at))
    return result.scalars().all()


@router.post("", response_model=PeerResponse, status_code=201)
async def create_peer(data: PeerCreate, db: AsyncSession = Depends(get_db)):
    # Сгенерировать ключи
    private_key, public_key = generate_keypair()
    preshared_key = generate_preshared_key()

    # Найти свободный IP
    result = await db.execute(select(Peer.assigned_ip))
    used = {row[0] for row in result.fetchall()}
    assigned_ip = get_next_ip(used)

    # Получить ключ сервера (или создать)
    server_key = await db.execute(
        select(ServerKey).where(ServerKey.interface == settings.wg_interface)
    )
    server_key = server_key.scalars().first()
    if not server_key:
        srv_priv, srv_pub = generate_keypair()  # из wireguard.py
        server_key = ServerKey(
            interface=settings.wg_interface,
            private_key=srv_priv,
            public_key=srv_pub,
        )
        db.add(server_key)
        await db.flush()

    # Создать пира в БД
    peer = Peer(
        name=data.name,
        public_key=public_key,
        private_key=private_key,
        preshared_key=preshared_key,
        assigned_ip=assigned_ip,
        speed_limit_mbps=data.speed_limit_mbps,
        data_quota_bytes=data.data_quota_bytes,
    )
    db.add(peer)
    await db.flush()

    # Пересобрать конфиг сервера и применить
    all_peers = await db.execute(select(Peer))
    peers_list = [
        {
            "public_key": p.public_key,
            "preshared_key": p.preshared_key,
            "assigned_ip": p.assigned_ip,
            "is_active": p.is_active,
        }
        for p in all_peers.scalars().all()
    ]
    server_conf = build_server_config(server_key.private_key, settings.wg_port, peers_list)
    apply_config(server_conf)

    # Применить лимит скорости
    init_shaper()
    if data.speed_limit_mbps > 0:
        apply_limit(assigned_ip, data.speed_limit_mbps)

    await db.commit()
    return peer


@router.patch("/{peer_id}", response_model=PeerResponse)
async def update_peer(peer_id: str, data: PeerUpdate, db: AsyncSession = Depends(get_db)):
    peer = await db.get(Peer, peer_id)
    if not peer:
        raise HTTPException(404, "Peer not found")

    old_limit = peer.speed_limit_mbps
    if data.name is not None:
        peer.name = data.name
    if data.is_active is not None:
        peer.is_active = data.is_active
    if data.speed_limit_mbps is not None:
        peer.speed_limit_mbps = data.speed_limit_mbps
    if data.data_quota_bytes is not None:
        peer.data_quota_bytes = data.data_quota_bytes

    # Если изменился лимит — обновить tc
    if data.speed_limit_mbps is not None and data.speed_limit_mbps != old_limit:
        if data.speed_limit_mbps > 0:
            apply_limit(peer.assigned_ip, data.speed_limit_mbps)
        else:
            remove_limit(peer.assigned_ip)

    # Если изменился is_active — пересобрать конфиг
    if data.is_active is not None:
        server_key = await db.execute(
            select(ServerKey).where(ServerKey.interface == settings.wg_interface)
        )
        server_key = server_key.scalars().first()
        all_peers = await db.execute(select(Peer))
        peers_list = [
            {
                "public_key": p.public_key,
                "preshared_key": p.preshared_key,
                "assigned_ip": p.assigned_ip,
                "is_active": p.is_active,
            }
            for p in all_peers.scalars().all()
        ]
        server_conf = build_server_config(server_key.private_key, settings.wg_port, peers_list)
        apply_config(server_conf)

    await db.commit()
    return peer


@router.delete("/{peer_id}", status_code=204)
async def delete_peer(peer_id: str, db: AsyncSession = Depends(get_db)):
    peer = await db.get(Peer, peer_id)
    if not peer:
        raise HTTPException(404, "Peer not found")

    remove_limit(peer.assigned_ip)

    await db.delete(peer)

    # Пересобрать конфиг без этого пира
    server_key = await db.execute(
        select(ServerKey).where(ServerKey.interface == settings.wg_interface)
    )
    server_key = server_key.scalars().first()
    all_peers = await db.execute(select(Peer))
    peers_list = [
        {
            "public_key": p.public_key,
            "preshared_key": p.preshared_key,
            "assigned_ip": p.assigned_ip,
            "is_active": p.is_active,
        }
        for p in all_peers.scalars().all()
    ]
    server_conf = build_server_config(server_key.private_key, settings.wg_port, peers_list)
    apply_config(server_conf)

    await db.commit()


@router.get("/{peer_id}/config", response_model=PeerConfig)
async def get_peer_config(peer_id: str, db: AsyncSession = Depends(get_db)):
    """Получить готовый конфиг для клиента."""
    peer = await db.get(Peer, peer_id)
    if not peer:
        raise HTTPException(404, "Peer not found")

    server_key = await db.execute(
        select(ServerKey).where(ServerKey.interface == settings.wg_interface)
    )
    server_key = server_key.scalars().first()

    config = build_client_config(
        client_private_key=peer.private_key,
        client_assigned_ip=peer.assigned_ip,
        server_public_key=server_key.public_key,
        server_endpoint=settings.wg_endpoint,
        preshared_key=peer.preshared_key,
    )
    return PeerConfig(config=config)
