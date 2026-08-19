import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.domain.instrument import UnitKind
from app.domain.provenance import FieldSource


class AssetType(str, enum.Enum):
    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[AssetType] = mapped_column(Enum(AssetType))
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="EUR", server_default="EUR")
    # How the price number reads. ``currency`` answers *which* currency and so
    # can't express "percent" or "no unit at all" — an index had to claim a
    # denomination it doesn't have. Only meaningful when unit_kind is CURRENCY.
    unit_kind: Mapped[UnitKind] = mapped_column(
        Enum(UnitKind), default=UnitKind.CURRENCY, server_default="CURRENCY",
    )
    # Provenance, per editable concept: did Fibenchi work this out, or did a
    # human say so? AUTO fields may be re-suggested when the guess improves;
    # USER fields are left alone. ``unit_source`` covers unit_kind *and*
    # currency — they're one decision ("how is this quoted"), not two.
    type_source: Mapped[FieldSource] = mapped_column(
        Enum(FieldSource), default=FieldSource.AUTO, server_default="AUTO",
    )
    unit_source: Mapped[FieldSource] = mapped_column(
        Enum(FieldSource), default=FieldSource.AUTO, server_default="AUTO",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    prices: Mapped[list["PriceHistory"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    annotations: Mapped[list["Annotation"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    note: Mapped["Note | None"] = relationship(back_populates="asset", cascade="all, delete-orphan", uselist=False)
    tags: Mapped[list["Tag"]] = relationship(secondary="tag_assets", lazy="selectin")
    theses: Mapped[list["Thesis"]] = relationship(secondary="thesis_assets", lazy="selectin")


# Avoid circular import issues - these are resolved at runtime
from app.models.annotation import Annotation  # noqa: E402, F401
from app.models.note import Note  # noqa: E402, F401
from app.models.price import PriceHistory  # noqa: E402, F401
from app.models.tag import Tag, tag_assets  # noqa: E402, F401
from app.models.thesis import Thesis, thesis_assets  # noqa: E402, F401
