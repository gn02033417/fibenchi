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
]
