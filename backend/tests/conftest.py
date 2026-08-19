import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.currency import Currency
from app.models.group import Group
from app.services.currency_service import load_cache as load_currency_cache
from app.services.price_providers import init_price_provider

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# SQLite ignores foreign-key constraints (and so ON DELETE CASCADE) unless asked
# per connection. Enable it so tests exercise the same cascade Postgres enforces
# in production — letting hard_delete_asset rely on the DB cascade the FKs
# already declare instead of hand-deleting every dependent table.
@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Currencies to seed in tests — subunits + common test currencies
_SEED_CURRENCIES = [
    Currency(code="USD", display_code="USD", divisor=1),
    Currency(code="EUR", display_code="EUR", divisor=1),
    Currency(code="GBP", display_code="GBP", divisor=1),
    Currency(code="GBp", display_code="GBP", divisor=100),
    Currency(code="GBX", display_code="GBP", divisor=100),
    Currency(code="ILS", display_code="ILS", divisor=1),
    Currency(code="ILA", display_code="ILS", divisor=100),
    Currency(code="ZAR", display_code="ZAR", divisor=1),
    Currency(code="ZAc", display_code="ZAR", divisor=100),
    Currency(code="KRW", display_code="KRW", divisor=1),
    Currency(code="JPY", display_code="JPY", divisor=1),
    Currency(code="CAD", display_code="CAD", divisor=1),
]


@pytest.fixture(autouse=True)
def reset_yahoo_throttle():
    """Disable inter-call spacing and clear breaker state between tests.

    The production throttle paces calls by 1s and trips the circuit
    breaker on Invalid Crumb. Both behaviours would slow the suite (and
    leak state across tests), so we run all tests with ``min_interval=0``
    and reset on entry.

    Also drops the client's cached ``Ticker`` so each test sees its own
    ``@patch("app.services.yahoo.client.Ticker")`` instead of a mock
    leaked from a prior test.
    """
    from app.services.yahoo import yahoo_client
    from app.services.yahoo.rate_limit import yahoo_throttle
    original_min_interval = yahoo_throttle._min_interval
    yahoo_throttle._min_interval = 0.0
    yahoo_throttle.reset()
    yahoo_client._invalidate_session()
    yield
    yahoo_throttle._min_interval = original_min_interval
    yahoo_throttle.reset()
    yahoo_client._invalidate_session()


@pytest.fixture(autouse=True)
def reset_stats_cache():
    """Clear the stats/data-health TTL cache between tests.

    It's module state with a 60s TTL, so without this a test that seeds its own
    collection silently reads the previous test's numbers — and only when run
    alongside them. Lives here rather than in the one test file that needs it
    today, so a future file hitting these endpoints can't inherit the hazard.
    """
    from app.services.stats_service import reset_stats_cache as _reset

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed the default Watchlist group (mirrors migration 0004) + currencies
    async with TestSession() as session:
        session.add(Group(name="Watchlist", is_default=True, position=0))
        for c in _SEED_CURRENCIES:
            session.add(Currency(code=c.code, display_code=c.display_code, divisor=c.divisor))
        await session.commit()
    # Populate in-memory currency cache
    async with TestSession() as session:
        await load_currency_cache(session)
    # Initialize price provider singleton (mirrors main.py lifespan)
    init_price_provider()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _clear_thesis_perf_cache():
    """The thesis-performance TTLCache is module-level and outlives the per-test
    in-memory DB (whose ids reset each test); clear it so one test can't read a
    colliding cache key written by another."""
    from app.services import thesis_service
    thesis_service._thesis_perf_cache.clear()
    yield


@pytest.fixture(autouse=True)
def _isolate_fundamentals_cache(monkeypatch):
    """Keep the fundamentals cache from leaking across tests.

    ``merge_fundamentals_*`` fire a background ``asyncio.create_task`` that hits
    the real Yahoo client on a cache miss. Left to run, that fire-and-forget
    task outlives the per-test event loop (``Task was destroyed but it is
    pending``) and its result lands in a module-level cache the next test can
    read — a nondeterministic cross-test coupling. Clear the module state and
    stub the scheduler to a no-op; tests that care about the merge behaviour
    patch the merge functions at their call sites instead."""
    from app.services import fundamentals_cache
    fundamentals_cache._fundamentals_cache.clear()
    fundamentals_cache._pending_symbols.clear()
    monkeypatch.setattr(fundamentals_cache, "_schedule_background_fetch", lambda *_a, **_k: None)
    yield
    fundamentals_cache._fundamentals_cache.clear()
    fundamentals_cache._pending_symbols.clear()


@pytest.fixture
async def db():
    async with TestSession() as session:
        yield session


@pytest.fixture
async def client(db):
    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
