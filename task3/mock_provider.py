import asyncio

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="Mock Streaming LLM Provider",
    version="1.0.0",
)


# ============================================================
# INPUT MODEL
# ============================================================

class GenerationRequest(
    BaseModel
):
    prompt: str


# ============================================================
# MOCK LLM STREAM
# ============================================================

async def mock_llm_stream():
    """
    Simulate an LLM streaming output.

    PII is intentionally split across separate chunks.

    This is important because a simple regex applied to each
    chunk independently would FAIL to catch these values.
    """

    chunks = [

        # Normal text + beginning of email
        "Hello. Your registered email is john.",

        # Middle of email
        "smith@example.",

        # End email + beginning SSN
        "com. Your SSN is 123-45-",

        # End SSN + beginning credit card
        "6789. Your card is 4111 1111 ",

        # End credit card
        "1111 1111. End of response.",
    ]


    for chunk in chunks:

        yield chunk


        # Simulate an actual model generating over time.

        await asyncio.sleep(
            0.25
        )


# ============================================================
# GENERATION ENDPOINT
# ============================================================

@app.post("/generate")
async def generate(
    request: GenerationRequest,
):
    """
    Mock provider generation endpoint.
    """

    return StreamingResponse(
        mock_llm_stream(),
        media_type="text/plain",
    )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "task3.mock_provider:app",
        host="127.0.0.1",
        port=9101,
        reload=False,
    )