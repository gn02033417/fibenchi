import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.instrument import UnitKind
from app.domain.provenance import FieldSource
from app.models.asset import AssetType
from app.services.currency_service import lookup as currency_lookup


class AssetCreate(BaseModel):
    symbol: str = Field(max_length=20, description="Ticker symbol (e.g. AAPL, VOO). Validated against Yahoo Finance.")
    name: str | None = Field(default=None, max_length=200, description="Display name. Auto-detected from Yahoo Finance if omitted.")
    type: AssetType | None = Field(
        default=None,
        description=(
            "Asset type. Omit to let Fibenchi decide (recorded as auto-detected, and "
            "re-suggested if the guess later improves); supplying one marks it as your "
            "choice, which suppresses suggestions against it."
        ),
    )


class AssetUpdate(BaseModel):
    """Partial update. Any field supplied here is recorded as a user choice, so
    Fibenchi stops suggesting alternatives for it."""

    name: str | None = Field(default=None, max_length=200, description="New display name.")
    type: AssetType | None = Field(default=None, description="Override asset type (stock/etf/index).")
    currency: str | None = Field(default=None, max_length=10, description="Override currency code (e.g. 'USD', 'EUR').")
    unit_kind: UnitKind | None = Field(
        default=None,
        description=(
            "Override how the price number reads: 'currency' (uses the currency field), "
            "'percent' (the number is a rate, e.g. a Treasury yield), or 'points' "
            "(an index level, no unit)."
        ),
    )


class AssetDetectionReset(BaseModel):
    """Which fields to hand back to auto-detection."""

    fields: list[str] = Field(
        default=["type", "unit_kind"],
        description="Field names to reset: 'type' and/or 'unit_kind'. Defaults to both.",
    )


class TagBrief(BaseModel):
    id: int = Field(description="Tag ID")
    name: str = Field(description="Tag label (e.g. 'tech', 'growth')")
    color: str = Field(description="Hex colour code (e.g. '#3b82f6')")

    model_config = {"from_attributes": True}


class AssetAttachments(BaseModel):
    """What is attached to an asset, for the remove dialog to warn before an orphan
    or a hard delete. ``groups`` drives the last-group warning; ``pseudo_etfs`` and
    ``theses`` are the silent-mutation risks a hard delete would cascade into."""

    symbol: str = Field(description="Ticker symbol")
    groups: list[str] = Field(default=[], description="Names of groups containing this asset")
    theses: list[str] = Field(default=[], description="Names of theses this asset is a member of")
    pseudo_etfs: list[str] = Field(default=[], description="Names of pseudo-ETFs this asset is a constituent of")
    tags: list[str] = Field(default=[], description="Tag names attached to this asset")
    has_note: bool = Field(default=False, description="Whether the asset has a non-empty note")
    annotation_count: int = Field(default=0, description="Number of chart annotations")


class AssetSuggestionResponse(BaseModel):
    """What Fibenchi reads the ticker as — advisory, never applied on its own.

    ``disagrees`` lists only fields that are still auto-detected *and* differ
    from what is stored; a field the user set never appears, however much the
    shape disagrees with it. An empty list means there is nothing to show.
    """

    type: AssetType = Field(description="Type the ticker's shape implies")
    unit_kind: UnitKind = Field(description="How the price number should read")
    currency: str | None = Field(default=None, description="Inferred currency, null for indices")
    differs: list[str] = Field(
        default=[],
        description=(
            "Fields where the shape meaningfully differs from the stored value, whoever "
            "set it. These are the fields that can be reset to auto-detection."
        ),
    )
    disagrees: list[str] = Field(
        default=[],
        description=(
            "The subset of 'differs' still auto-detected — what may be surfaced "
            "unprompted. A user-set field never appears here."
        ),
    )


class AssetResponse(BaseModel):
    id: int = Field(description="Internal asset ID")
    symbol: str = Field(description="Ticker symbol")
    name: str = Field(description="Display name")
    type: AssetType = Field(description="Asset type: stock or etf")
    exchange: str | None = Field(default=None, description="Verified exchange (e.g. TSE or OTC)")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    unit_kind: UnitKind = Field(
        default=UnitKind.CURRENCY,
        description="How the price number reads: currency, percent, or points",
    )
    type_source: FieldSource = Field(default=FieldSource.AUTO, description="Who set 'type': auto or user")
    unit_source: FieldSource = Field(
        default=FieldSource.AUTO, description="Who set 'unit_kind'/'currency': auto or user",
    )
    suggested: AssetSuggestionResponse | None = Field(
        default=None, description="Fibenchi's read on this ticker",
    )
    created_at: datetime.datetime = Field(description="Timestamp when the asset was first added")
    tags: list[TagBrief] = Field(default=[], description="Tags attached to this asset")

    model_config = {"from_attributes": True}

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Convert raw Yahoo code (e.g. 'GBp') to display code ('GBP') for API responses."""
        display, _ = currency_lookup(v)
        return display

    @model_validator(mode="after")
    def derive_suggestion(self):
        """Compute the suggestion here rather than in each router.

        Every field it needs is already on this model, and attaching it
        per-endpoint meant an asset served through /api/groups arrived with
        ``suggested: null`` — so the edit dialog, which reads group data, could
        never show one. Deriving it in the schema makes that unforgettable.
        """
        # Imported here: app.services imports app.schemas, so a module-level
        # import would close the loop.
        from app.services.asset_suggestion import suggest_for_asset

        if self.suggested is None:
            self.suggested = AssetSuggestionResponse.model_validate(
                suggest_for_asset(self), from_attributes=True,
            )
        return self
