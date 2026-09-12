import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Peer(Base):
    __tablename__ = "peers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    private_key: Mapped[str] = mapped_column(String(64), nullable=False)
    preshared_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_ip: Mapped[str] = mapped_column(String(15), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    speed_limit_mbps: Mapped[int] = mapped_column(Integer, default=0)  # 0 = без лимита
    data_quota_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # 0 = без квоты
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_handshake: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stats: Mapped[list["TrafficStat"]] = relationship(back_populates="peer", cascade="all, delete-orphan")


class TrafficStat(Base):
    __tablename__ = "traffic_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    peer_id: Mapped[str] = mapped_column(ForeignKey("peers.id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    peer: Mapped[Peer] = relationship(back_populates="stats")


class ServerKey(Base):
    """Приватный и публичный ключ серверного интерфейса."""
    __tablename__ = "server_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interface: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    private_key: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
