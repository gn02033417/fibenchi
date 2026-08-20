from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.schemas.quote import QuoteResponse
from app.services import quote_service

router = APIRouter(prefix="/api", tags=["quotes"])


@router.get("/quotes", response_model=list[QuoteResponse], summary="Get real-time quotes for symbols")
async def get_quotes(symbols: str = Query(..., description="Comma-separated list of symbols")):
    """Fetch latest Taiwan market snapshots for one or more symbols.

    Pass a comma-separated list of ticker symbols (e.g. `AAPL,MSFT,GOOGL`).
    Returns normalized price, freshness status, timestamp, and market fields.
    """
    return await quote_service.get_quotes(symbols)


@router.get(
    "/quotes/stream",
    summary="SSE stream of grouped asset quotes (delta compressed)",
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events stream. The first `quotes` event is the current grouped-asset snapshot; later events contain only changed symbols from the in-memory live quote state. `event: intraday` is sent only when the `intraday` query param names symbols."}},
)
async def stream_quotes(
    intraday: str | None = Query(
        None,
        description=(
            "Comma-separated symbols to also receive 1-minute bars for "
            "(`event: intraday`). Omit for none — bars are opt-in because the "
            "first frame is large and most views never draw them."
        ),
    ),
):
    """Open a Server-Sent Events stream that pushes real-time quotes for all
    assets that belong to at least one group.

    **Delta compression:** After the initial full payload, only symbols whose
    data has changed since the previous push are included — reducing bandwidth
    when prices are stable or markets are closed.

    **Event-driven state:** opening this browser stream never starts a price
    provider polling loop. Updates arrive only when the shared Shioaji live
    quote state changes.

    Each SSE event uses `event: quotes` with a JSON object keyed by symbol.

    **Intraday bars** arrive as a separate `event: intraday`, and only for the
    symbols named in the `intraday` param. Quotes are small and every page
    shows them; a full bar set is neither. To change the selection, reopen the
    stream with a different param — the new connection's first push carries
    the full window for the newly requested symbols.
    """
    symbols = frozenset(s.strip().upper() for s in (intraday or "").split(",") if s.strip())
    return StreamingResponse(
        quote_service.quote_event_generator(symbols),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
