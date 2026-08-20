"""Typed async HTTP client for the official Shioaji sidecar server."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING, TypeVar

import httpx
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.config import settings

if TYPE_CHECKING:
    from app.services.shioaji.kbars import MinuteBar
    from app.services.shioaji.quotes import ShioajiSnapshot


class ShioajiClientError(RuntimeError):
    """Base error for failures at the Shioaji sidecar boundary."""


class ShioajiTimeoutError(ShioajiClientError):
    """The sidecar did not respond within the configured timeout."""


class ShioajiUnavailableError(ShioajiClientError):
    """The sidecar could not be reached."""


class ShioajiHTTPError(ShioajiClientError):
    """The sidecar returned a non-success HTTP response."""

    def __init__(self, status_code: int, path: str):
        self.status_code = status_code
        self.path = path
        super().__init__(f"Shioaji sidecar returned HTTP {status_code} for {path}")


class ShioajiPayloadError(ShioajiClientError):
    """The sidecar response did not match the typed boundary contract."""

    def __init__(self, path: str, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"Invalid Shioaji response for {path}: {cause}")


class ShioajiHealth(BaseModel):
    healthy: bool | None = None
    status: str | None = None
    simulation: bool | None = None

    model_config = ConfigDict(extra="ignore")


class ShioajiInfo(BaseModel):
    name: str
    version: str
    protocols: list[str] = Field(default_factory=list)
    simulation: bool | None = None

    model_config = ConfigDict(extra="ignore")


class ShioajiStreamStatus(BaseModel):
    active_connections: int = 0
    timestamp: datetime | None = None
    status: str

    model_config = ConfigDict(extra="ignore")


class ShioajiContract(BaseModel):
    security_type: StrictStr
    region: StrictStr | None = None
    exchange: StrictStr
    code: StrictStr
    target_code: StrictStr | None = None

    model_config = ConfigDict(extra="ignore")


class ShioajiContractsPage(BaseModel):
    contracts: list[ShioajiContract]
    security_type: StrictStr | None = None
    region: StrictStr | None = None
    page: int | None = None
    page_size: int | None = None
    max_page: int | None = None
    total: int | None = None

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def accept_full_contract_list(cls, value):
        if isinstance(value, list):
            return {"contracts": value}
        return value


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class ShioajiClient:
    """Typed read-only HTTP client for the isolated Shioaji server."""

    HEALTH_PATH = "/api/v1/health"
    INFO_PATH = "/api/v1/info"
    STREAM_STATUS_PATH = "/api/v1/stream/status"
    CONTRACTS_PATH = "/api/v1/data/contracts"
    KBARS_PATH = "/api/v1/data/kbars"
    SNAPSHOTS_PATH = "/api/v1/data/snapshots"

    def __init__(
        self,
        base_url: str | AnyHttpUrl | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        raw_base_url = base_url or settings.shioaji_base_url
        try:
            self.base_url: AnyHttpUrl = TypeAdapter(AnyHttpUrl).validate_python(raw_base_url)
        except ValidationError as exc:
            raise ValueError("SHIOAJI_BASE_URL must be a valid HTTP(S) URL") from exc

        raw_timeout = timeout if timeout is not None else settings.shioaji_timeout_seconds
        if isinstance(raw_timeout, httpx.Timeout):
            self.timeout = raw_timeout
        else:
            if raw_timeout <= 0:
                raise ValueError("Shioaji timeout must be greater than zero")
            self.timeout = httpx.Timeout(raw_timeout)
        self._transport = transport

    async def health(self) -> ShioajiHealth:
        return await self._get(self.HEALTH_PATH, ShioajiHealth)

    async def info(self) -> ShioajiInfo:
        return await self._get(self.INFO_PATH, ShioajiInfo)

    async def stream_status(self) -> ShioajiStreamStatus:
        return await self._get(self.STREAM_STATUS_PATH, ShioajiStreamStatus)

    async def list_contracts(
        self,
        security_type: str = "STK",
        *,
        page: int | None = None,
        page_size: int | None = None,
    ) -> ShioajiContractsPage:
        """List sidecar contracts, using full or paginated mode."""
        params: dict[str, str | int] = {"security_type": security_type}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["page_size"] = page_size
        return await self._get(self.CONTRACTS_PATH, ShioajiContractsPage, params=params)

    async def snapshots(
        self, contracts: list[Mapping[str, str]]
    ) -> list["ShioajiSnapshot"]:
        """Fetch one request-type snapshot batch from the sidecar."""
        from app.services.shioaji.quotes import ShioajiSnapshotsResponse

        response = await self._post(
            self.SNAPSHOTS_PATH,
            ShioajiSnapshotsResponse,
            payload={"contracts": [dict(contract) for contract in contracts]},
        )
        return response.snapshots

    async def kbars(
        self,
        contract: Mapping[str, str],
        *,
        start: date,
        end: date,
    ) -> list["MinuteBar"]:
        """Fetch and normalize one official Shioaji Kbars date range."""
        from app.services.shioaji.kbars import ShioajiKbarsResponse

        response = await self._post(
            self.KBARS_PATH,
            ShioajiKbarsResponse,
            payload={
                "contract": dict(contract),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        return response.minute_bars()

    async def _get(
        self,
        path: str,
        model: type[ResponseModel],
        *,
        params: Mapping[str, object] | None = None,
    ) -> ResponseModel:
        try:
            async with httpx.AsyncClient(
                base_url=str(self.base_url),
                timeout=self.timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ShioajiTimeoutError(f"Shioaji sidecar timed out for {path}") from exc
        except httpx.RequestError as exc:
            raise ShioajiUnavailableError(f"Shioaji sidecar unavailable for {path}") from exc

        if response.is_error:
            raise ShioajiHTTPError(response.status_code, path)

        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ShioajiPayloadError(path, exc) from exc

    async def _post(
        self,
        path: str,
        model: type[ResponseModel],
        *,
        payload: object,
    ) -> ResponseModel:
        try:
            async with httpx.AsyncClient(
                base_url=str(self.base_url),
                timeout=self.timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ShioajiTimeoutError(f"Shioaji sidecar timed out for {path}") from exc
        except httpx.RequestError as exc:
            raise ShioajiUnavailableError(f"Shioaji sidecar unavailable for {path}") from exc

        if response.is_error:
            raise ShioajiHTTPError(response.status_code, path)

        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ShioajiPayloadError(path, exc) from exc
