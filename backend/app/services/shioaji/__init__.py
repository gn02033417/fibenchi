"""HTTP boundary for the isolated Shioaji sidecar."""

from app.services.shioaji.client import (
    ShioajiClient,
    ShioajiClientError,
    ShioajiContract,
    ShioajiContractsPage,
    ShioajiHealth,
    ShioajiHTTPError,
    ShioajiInfo,
    ShioajiPayloadError,
    ShioajiStreamStatus,
    ShioajiTimeoutError,
    ShioajiUnavailableError,
)
from app.services.shioaji.contracts import (
    ShioajiContractsAdapter,
    ShioajiContractSyncError,
    TaiwanContract,
    fetch_stk_contracts,
)
from app.services.shioaji.kbars import MinuteBar, ShioajiKbarsResponse
from app.services.shioaji.quotes import (
    ShioajiSnapshot,
    ShioajiSnapshotsResponse,
    map_snapshot_to_quote,
)
from app.services.shioaji.stream import (
    ShioajiQuoteEvent,
    ShioajiQuoteStream,
    ShioajiQuoteSubscription,
    ShioajiQuoteUpdate,
    map_quote_event_to_quote,
    map_quote_event_to_update,
)

__all__ = [
    "ShioajiClient",
    "ShioajiClientError",
    "ShioajiContract",
    "ShioajiContractsPage",
    "ShioajiContractSyncError",
    "ShioajiContractsAdapter",
    "ShioajiHealth",
    "ShioajiHTTPError",
    "ShioajiInfo",
    "ShioajiPayloadError",
    "ShioajiStreamStatus",
    "ShioajiTimeoutError",
    "ShioajiUnavailableError",
    "TaiwanContract",
    "fetch_stk_contracts",
    "MinuteBar",
    "ShioajiKbarsResponse",
    "ShioajiSnapshot",
    "ShioajiSnapshotsResponse",
    "map_snapshot_to_quote",
    "ShioajiQuoteEvent",
    "ShioajiQuoteUpdate",
    "ShioajiQuoteStream",
    "ShioajiQuoteSubscription",
    "map_quote_event_to_update",
    "map_quote_event_to_quote",
]
