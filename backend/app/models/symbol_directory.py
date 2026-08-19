from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

TAIWAN_EXCHANGES = frozenset({"TSE", "OTC"})


class SymbolDirectory(Base):
    __tablename__ = "symbol_directory"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    exchange: Mapped[str] = mapped_column(String(100), default="")
    type: Mapped[str] = mapped_column(String(10), default="stock")
    currency: Mapped[str] = mapped_column(String(10), default="USD", server_default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    contract_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reference_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("symbol_sources.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def is_taiwan(self) -> bool:
        """Whether this directory row belongs to the supported Taiwan venues."""
        return self.exchange in TAIWAN_EXCHANGES
