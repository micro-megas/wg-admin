from datetime import datetime
from pydantic import BaseModel, Field


# --- Peer ---

class PeerCreate(BaseModel):
    name: str = Field(..., max_length=100)
    speed_limit_mbps: int = Field(default=0, ge=0)
    data_quota_bytes: int = Field(default=0, ge=0)


class PeerUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    speed_limit_mbps: int | None = Field(default=None, ge=0)
    data_quota_bytes: int | None = Field(default=None, ge=0)


class PeerResponse(BaseModel):
    id: str
    name: str
    public_key: str
    assigned_ip: str
    is_active: bool
    speed_limit_mbps: int
    data_quota_bytes: int
    created_at: datetime
    last_handshake: datetime | None
    rx_bytes: int = 0
    tx_bytes: int = 0

    class Config:
        from_attributes = True


class PeerConfig(BaseModel):
    """Готовый конфиг для клиента (вставляется в .conf-файл)."""
    config: str
    qr_code_base64: str | None = None  # если захотите генерировать QR


# --- Stats ---

class StatsResponse(BaseModel):
    peer_id: str
    name: str
    assigned_ip: str
    is_active: bool
    last_handshake: datetime | None
    rx_bytes: int
    tx_bytes: int
    speed_limit_mbps: int
    data_quota_bytes: int
    data_used_bytes: int


# --- Health ---

class HealthResponse(BaseModel):
    status: str
    interface: str
    is_up: bool
    peers_online: int
    peers_total: int
