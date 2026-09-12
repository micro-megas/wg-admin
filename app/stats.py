import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.database import async_session
from app.models import Peer, TrafficStat, ServerKey
from app.wireguard import parse_wg_show
from app.config import settings

logger = logging.getLogger("wg-agent.stats")


async def collect_stats():
    """Периодически собирать статистику wg show и писать в БД."""
    while True:
        try:
            raw = parse_wg_show()
            async with async_session() as db:
                result = await db.execute(select(Peer))
                peers = result.scalars().all()

                for peer in peers:
                    info = raw.get(peer.public_key)
                    if not info:
                        continue

                    stat = TrafficStat(
                        peer_id=peer.id,
                        rx_bytes=info["rx"],
                        tx_bytes=info["tx"],
                    )
                    db.add(stat)
                    peer.last_handshake = datetime.now(timezone.utc) if info.get("last_handshake") else None

                await db.commit()
            logger.info("Stats collected for %d peers", len(raw))

        except Exception as e:
            logger.error("Stats collection error: %s", e)

        await asyncio.sleep(settings.stats_interval)


def start_stats_collector():
    asyncio.create_task(collect_stats())
