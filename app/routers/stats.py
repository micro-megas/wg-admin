from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import Peer, TrafficStat
from app.schemas import StatsResponse
from app.wireguard import parse_wg_show

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=list[StatsResponse])
async def get_stats(db: AsyncSession = Depends(get_db)):
    raw = parse_wg_show()
    result = await db.execute(select(Peer).order_by(Peer.name))
    peers = result.scalars().all()

    response = []
    for peer in peers:
        info = raw.get(peer.public_key, {})

        # Суммарный трафик из БД
        total = await db.execute(
            select(func.coalesce(func.sum(TrafficStat.rx_bytes), 0)).where(TrafficStat.peer_id == peer.id)
        )
        rx_total = total.scalar()
        total = await db.execute(
            select(func.coalesce(func.sum(TrafficStat.tx_bytes), 0)).where(TrafficStat.peer_id == peer.id)
        )
        tx_total = total.scalar()

        response.append(StatsResponse(
            peer_id=peer.id,
            name=peer.name,
            assigned_ip=peer.assigned_ip,
            is_active=peer.is_active,
            last_handshake=peer.last_handshake,
            rx_bytes=info.get("rx", 0),
            tx_bytes=info.get("tx", 0),
            speed_limit_mbps=peer.speed_limit_mbps,
            data_quota_bytes=peer.data_quota_bytes,
            data_used_bytes=rx_total + tx_total,
        ))
    return response
