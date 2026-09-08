import pytest

from task4.providers import (
    ProviderFailure,
    ProviderRateLimited,
    ProviderTimeout,
)
from task4.rate_limiter import (
    RateLimitExceeded,
    SQLiteTokenRateLimiter,
)
from task4.router import (
    AllProvidersFailed,
    CompletionRouter,
)


class FakeProvider:
    def __init__(
        self,
        result=None,
        error=None,
    ):
        self.result = result
        self.error = error
        self.called = 0

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
    ):
        self.called += 1

        if self.error is not None:
            raise self.error

        return self.result


@pytest.mark.asyncio
async def test_primary_success_does_not_call_secondary():
    primary = FakeProvider(
        result={
            "provider": "primary",
            "text": "primary response",
        }
    )

    secondary = FakeProvider(
        result={
            "provider": "secondary",
            "text": "secondary response",
        }
    )

    router = CompletionRouter(primary, secondary)

    result = await router.complete(
        "hello",
        100,
    )

    assert result["provider"] == "primary"
    assert primary.called == 1
    assert secondary.called == 0


@pytest.mark.asyncio
async def test_primary_429_falls_back_to_secondary():
    primary = FakeProvider(
        error=ProviderRateLimited(
            "primary rate limited"
        )
    )

    secondary = FakeProvider(
        result={
            "provider": "secondary",
            "text": "fallback response",
        }
    )

    router = CompletionRouter(primary, secondary)

    result = await router.complete(
        "hello",
        100,
    )

    assert result["provider"] == "secondary"
    assert primary.called == 1
    assert secondary.called == 1


@pytest.mark.asyncio
async def test_primary_timeout_falls_back_to_secondary():
    primary = FakeProvider(
        error=ProviderTimeout(
            "primary timed out"
        )
    )

    secondary = FakeProvider(
        result={
            "provider": "secondary",
            "text": "fallback response",
        }
    )

    router = CompletionRouter(primary, secondary)

    result = await router.complete(
        "hello",
        100,
    )

    assert result["provider"] == "secondary"
    assert primary.called == 1
    assert secondary.called == 1


@pytest.mark.asyncio
async def test_primary_generic_failure_does_not_fallback():
    primary = FakeProvider(
        error=ProviderFailure(
            "internal upstream stack trace"
        )
    )

    secondary = FakeProvider(
        result={
            "provider": "secondary",
        }
    )

    router = CompletionRouter(primary, secondary)

    with pytest.raises(AllProvidersFailed):
        await router.complete(
            "hello",
            100,
        )

    assert primary.called == 1
    assert secondary.called == 0


@pytest.mark.asyncio
async def test_secondary_failure_becomes_gateway_failure():
    primary = FakeProvider(
        error=ProviderRateLimited(
            "primary rate limited"
        )
    )

    secondary = FakeProvider(
        error=ProviderFailure(
            "secondary internal failure"
        )
    )

    router = CompletionRouter(primary, secondary)

    with pytest.raises(AllProvidersFailed):
        await router.complete(
            "hello",
            100,
        )

    assert primary.called == 1
    assert secondary.called == 1


def test_rate_limiter_tracks_each_tenant_separately(
    tmp_path,
):
    db_path = tmp_path / "rate_limit.db"

    limiter = SQLiteTokenRateLimiter(
        str(db_path),
        token_limit=50_000,
        window_seconds=60,
    )

    limiter.reserve(
        "tenant-a",
        40_000,
    )

    limiter.reserve(
        "tenant-b",
        40_000,
    )

    assert limiter.current_usage(
        "tenant-a"
    ) == 40_000

    assert limiter.current_usage(
        "tenant-b"
    ) == 40_000


def test_rate_limiter_rejects_over_limit(
    tmp_path,
):
    db_path = tmp_path / "rate_limit.db"

    limiter = SQLiteTokenRateLimiter(
        str(db_path),
        token_limit=50_000,
        window_seconds=60,
    )

    limiter.reserve(
        "tenant-a",
        40_000,
    )

    with pytest.raises(
        RateLimitExceeded
    ):
        limiter.reserve(
            "tenant-a",
            10_001,
        )


def test_rate_limiter_allows_exact_limit(
    tmp_path,
):
    db_path = tmp_path / "rate_limit.db"

    limiter = SQLiteTokenRateLimiter(
        str(db_path),
        token_limit=50_000,
        window_seconds=60,
    )

    limiter.reserve(
        "tenant-a",
        40_000,
    )

    limiter.reserve(
        "tenant-a",
        10_000,
    )

    assert limiter.current_usage(
        "tenant-a"
    ) == 50_000


def test_reconcile_changes_reserved_usage(
    tmp_path,
):
    db_path = tmp_path / "rate_limit.db"

    limiter = SQLiteTokenRateLimiter(
        str(db_path),
        token_limit=50_000,
        window_seconds=60,
    )

    reservation = limiter.reserve(
        "tenant-a",
        10_000,
    )

    assert limiter.current_usage(
        "tenant-a"
    ) == 10_000

    limiter.reconcile(
        reservation,
        2_500,
    )

    assert limiter.current_usage(
        "tenant-a"
    ) == 2_500


def test_release_removes_reservation(
    tmp_path,
):
    db_path = tmp_path / "rate_limit.db"

    limiter = SQLiteTokenRateLimiter(
        str(db_path),
        token_limit=50_000,
        window_seconds=60,
    )

    reservation = limiter.reserve(
        "tenant-a",
        10_000,
    )

    limiter.release(reservation)

    assert limiter.current_usage(
        "tenant-a"
    ) == 0