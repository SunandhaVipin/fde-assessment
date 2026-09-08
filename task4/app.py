import logging
import sys
import uuid
from contextlib import asynccontextmanager

import tiktoken
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from task4.providers import ModelProvider
from task4.rate_limiter import RateLimitExceeded, SQLiteTokenRateLimiter
from task4.router import AllProvidersFailed, CompletionRouter


logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("llm-gateway")


TOKEN_LIMIT = 50_000
WINDOW_SECONDS = 60

PRIMARY_URL = "http://127.0.0.1:9201/complete"
SECONDARY_URL = "http://127.0.0.1:9202/complete"

DB_PATH = "rate_limit.db"


class CompletionRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(
        default=500,
        gt=0,
        le=10_000,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    limiter = SQLiteTokenRateLimiter(
        db_path=DB_PATH,
        token_limit=TOKEN_LIMIT,
        window_seconds=WINDOW_SECONDS,
    )

    primary = ModelProvider(
        name="primary",
        base_url=PRIMARY_URL,
        timeout_seconds=3.0,
    )

    secondary = ModelProvider(
        name="secondary",
        base_url=SECONDARY_URL,
        timeout_seconds=3.0,
    )

    router = CompletionRouter(
        primary=primary,
        secondary=secondary,
    )

    encoder = tiktoken.get_encoding(
        "cl100k_base"
    )

    app.state.limiter = limiter
    app.state.router = router
    app.state.encoder = encoder

    logger.info("Gateway initialized")

    yield

    logger.info("Gateway shutting down")


app = FastAPI(
    title="Resilient LLM Gateway",
    version="1.0.0",
    lifespan=lifespan,
)


def estimate_input_tokens(
    prompt: str,
) -> int:
    return len(
        app.state.encoder.encode(prompt)
    )


def sanitized_error(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )


@app.post("/v1/completions")
async def completions(
    request: CompletionRequest,
    x_api_key: str | None = Header(
        default=None,
        alias="x-api-key",
    ),
):
    request_id = str(uuid.uuid4())

    if not x_api_key:
        return sanitized_error(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing API key",
            request_id=request_id,
        )

    input_tokens = estimate_input_tokens(
        request.prompt
    )

    estimated_total = (
        input_tokens
        + request.max_tokens
    )

    try:
        reservation_id = (
            app.state.limiter.reserve(
                tenant_key=x_api_key,
                tokens=estimated_total,
            )
        )

    except RateLimitExceeded:
        return sanitized_error(
            status_code=429,
            code="RATE_LIMIT_EXCEEDED",
            message=(
                "Token rate limit exceeded"
            ),
            request_id=request_id,
        )

    except Exception:
        logger.exception(
            "Rate limiter failure"
        )

        return sanitized_error(
            status_code=500,
            code="INTERNAL_ERROR",
            message=(
                "Gateway request failed"
            ),
            request_id=request_id,
        )

    try:
        result = await (
            app.state.router.complete(
                prompt=request.prompt,
                max_tokens=request.max_tokens,
            )
        )

    except AllProvidersFailed:
        app.state.limiter.release(
            reservation_id
        )

        logger.warning(
            "All providers failed "
            "request_id=%s",
            request_id,
        )

        return sanitized_error(
            status_code=503,
            code="UPSTREAM_UNAVAILABLE",
            message=(
                "Completion service "
                "temporarily unavailable"
            ),
            request_id=request_id,
        )

    except Exception:
        app.state.limiter.release(
            reservation_id
        )

        logger.exception(
            "Unexpected gateway failure "
            "request_id=%s",
            request_id,
        )

        return sanitized_error(
            status_code=500,
            code="INTERNAL_ERROR",
            message=(
                "Gateway request failed"
            ),
            request_id=request_id,
        )

    usage = result.get(
        "usage",
        {},
    )

    actual_tokens = usage.get(
        "total_tokens"
    )

    if (
        isinstance(actual_tokens, int)
        and actual_tokens >= 0
    ):
        try:
            app.state.limiter.reconcile(
                reservation_id,
                actual_tokens,
            )

        except Exception:
            logger.exception(
                "Failed to reconcile "
                "token reservation"
            )

    return {
        "request_id": request_id,
        "provider": result.get(
            "provider"
        ),
        "text": result.get(
            "text"
        ),
        "usage": usage,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "task4.app:app",
        host="127.0.0.1",
        port=9200,
        reload=False,
    )