import asyncio
import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class ProviderRateLimited(Exception):
    pass


class ProviderTimeout(Exception):
    pass


class ProviderFailure(Exception):
    pass


class ModelProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
    ) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                response = await asyncio.wait_for(
                    client.post(
                        self.base_url,
                        json={
                            "prompt": prompt,
                            "max_tokens": max_tokens,
                        },
                    ),
                    timeout=self.timeout_seconds,
                )

        except asyncio.TimeoutError as exc:
            raise ProviderTimeout(
                f"{self.name} timed out"
            ) from exc

        except httpx.RequestError as exc:
            raise ProviderFailure(
                f"{self.name} request failed"
            ) from exc

        if response.status_code == 429:
            raise ProviderRateLimited(
                f"{self.name} rate limited"
            )

        if response.status_code >= 400:
            raise ProviderFailure(
                f"{self.name} returned an upstream error"
            )

        try:
            return response.json()

        except ValueError as exc:
            raise ProviderFailure(
                f"{self.name} returned invalid JSON"
            ) from exc


# ------------------------------------------------------------------
# Mock provider used only for local assessment testing
# ------------------------------------------------------------------

mock_app = FastAPI(
    title="Mock LLM Provider",
    version="1.0.0",
)


class MockCompletionRequest(BaseModel):
    prompt: str
    max_tokens: int = 1000


@mock_app.post("/complete")
async def mock_complete(
    request: MockCompletionRequest,
):
    provider_name = os.getenv(
        "MOCK_PROVIDER_NAME",
        "primary",
    )

    # Simulate primary-provider HTTP 429
    if (
        provider_name == "primary"
        and "force_429" in request.prompt.lower()
    ):
        raise HTTPException(
            status_code=429,
            detail="Provider rate limit",
        )

    # Simulate primary-provider timeout
    if (
        provider_name == "primary"
        and "force_timeout" in request.prompt.lower()
    ):
        await asyncio.sleep(4.0)

    # Optional generic failure scenario
    if (
        provider_name == "primary"
        and "force_error" in request.prompt.lower()
    ):
        raise HTTPException(
            status_code=500,
            detail="Internal provider failure",
        )

    # Simple deterministic mock token accounting.
    input_tokens = max(
        1,
        len(request.prompt.split()),
    )

    output_text = (
        f"Completion from {provider_name}: "
        f"{request.prompt}"
    )

    output_tokens = max(
        1,
        len(output_text.split()),
    )

    total_tokens = input_tokens + output_tokens

    return {
        "provider": provider_name,
        "text": output_text,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "task4.providers:mock_app",
        host="127.0.0.1",
        port=9201,
        reload=False,
    )