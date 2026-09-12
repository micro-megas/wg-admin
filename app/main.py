import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Security, HTTPException
from fastapi.security import APIKeyHeader
from app.config import settings
from app.database import init_db
from app.stats import start_stats_collector
from app.routers import peers, stats
from app.schemas import HealthResponse
from app.wireguard import parse_wg_show

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wg-agent")

api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(401, "Invalid API key")
    return api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_stats_collector()
    logger.info("WG Agent started")
    yield


app = FastAPI(
    title="WireGuard Agent",
    version="0.1.0",
    lifespan=lifespan,
)


# Защита всех эндпоинтов API-ключом
app.include_router(peers.router, dependencies=[Security(verify_api_key)])
app.include_router(stats.router, dependencies=[Security(verify_api_key)])


@app.get("/api/health", response_model=HealthResponse)
async def health():
    raw = parse_wg_show()
    return HealthResponse(
        status="ok",
        interface=settings.wg_interface,
        is_up=len(raw) > 0,
        peers_online=len(raw),
        peers_total=0,  # можно вычислить из БД
    )
