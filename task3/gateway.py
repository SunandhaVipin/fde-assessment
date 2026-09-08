import logging
import sys
from collections.abc import AsyncIterator

import httpx

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from task3.redactor import StreamingRedactor


# ============================================================
# CONFIGURATION
# ============================================================

PROVIDER_URL = (
    "http://127.0.0.1:9101/generate"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "llm-guardrail-gateway"
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="Streaming LLM Guardrail Gateway",
    version="1.0.0",
)


# ============================================================
# REQUEST MODEL
# ============================================================

class GenerationRequest(
    BaseModel
):
    prompt: str


# ============================================================
# STREAMING PROXY
# ============================================================

async def stream_guarded_response(
    prompt: str,
) -> AsyncIterator[str]:
    """
    Stream an LLM response through the PII guardrail.

    Important:

        We DO NOT do:

            response.text

        or:

            await response.aread()

    because those approaches buffer the full response.

    Instead we consume:

        response.aiter_text()

    chunk-by-chunk.
    """

    redactor = StreamingRedactor()


    try:

        async with httpx.AsyncClient(
            timeout=None,
        ) as client:


            # ------------------------------------------------
            # Open a streaming connection to the provider
            # ------------------------------------------------

            async with client.stream(
                "POST",
                PROVIDER_URL,
                json={
                    "prompt": prompt,
                },
            ) as response:


                response.raise_for_status()


                logger.info(
                    "Connected to streaming provider"
                )


                # ============================================
                # STREAM CHUNK-BY-CHUNK
                # ============================================

                async for chunk in (
                    response.aiter_text()
                ):


                    # ----------------------------------------
                    # Run each incoming piece through our
                    # stateful redactor.
                    # ----------------------------------------

                    safe_text = (
                        redactor.push(
                            chunk
                        )
                    )


                    # ----------------------------------------
                    # Send safe text immediately.
                    # ----------------------------------------

                    if safe_text:

                        yield safe_text


                # ============================================
                # PROVIDER FINISHED
                # ============================================

                remaining = (
                    redactor.flush()
                )


                if remaining:

                    yield remaining


    except httpx.TimeoutException:

        logger.error(
            "LLM provider timed out"
        )

        yield (
            "\n[Gateway error: "
            "provider unavailable]\n"
        )


    except httpx.HTTPError:

        logger.exception(
            "LLM provider request failed"
        )

        yield (
            "\n[Gateway error: "
            "provider unavailable]\n"
        )


# ============================================================
# GATEWAY ENDPOINT
# ============================================================

@app.post("/v1/generate")
async def generate(
    request: GenerationRequest,
):
    """
    Route generation through the streaming PII guardrail.
    """

    logger.info(
        "Generation request received"
    )


    return StreamingResponse(
        stream_guarded_response(
            request.prompt
        ),
        media_type="text/plain",
        headers={
            # Helps discourage proxy buffering.
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "task3.gateway:app",
        host="127.0.0.1",
        port=9100,
        reload=False,
    )