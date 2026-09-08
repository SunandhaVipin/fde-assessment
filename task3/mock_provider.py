import asyncio

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel



app = FastAPI(
    title="Mock Streaming LLM Provider",
    version="1.0.0",
)




class GenerationRequest(
    BaseModel
):
    prompt: str




async def mock_llm_stream():
    """
    Simulate an LLM streaming output.

    PII is intentionally split across separate chunks.

    This is important because a simple regex applied to each
    chunk independently would FAIL to catch these values.
    """

    chunks = [

        
        "Hello. Your registered email is john.",

       
        "smith@example.",

        "com. Your SSN is 123-45-",

        "6789. Your card is 4111 1111 ",

        "1111 1111. End of response.",
    ]


    for chunk in chunks:

        yield chunk



        await asyncio.sleep(
            0.25
        )




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



if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "task3.mock_provider:app",
        host="127.0.0.1",
        port=9101,
        reload=False,
    )
