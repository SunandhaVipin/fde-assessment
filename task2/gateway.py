import logging
import sys
from typing import Any

import httpx

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


DOWNSTREAM_URL = "http://127.0.0.1:9001/mcp"



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
    "mcp-gateway"
)



app = FastAPI(
    title="MCP Authorization Gateway",
    version="1.0.0",
)





TOKEN_ROLES = {
    "viewer-token": "viewer",
    "admin-token": "admin",
}




PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INVALID_PARAMS = -32602

UNAUTHORIZED_TOOL_CALL = -32001
DOWNSTREAM_UNAVAILABLE = -32000




def jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
) -> dict[str, Any]:
    """
    Build a JSON-RPC 2.0 error response.
    """

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }



def extract_role(
    authorization_header: str | None,
) -> str | None:
    """
    Extract role from:

        Authorization: Bearer <token>

    Supported demo tokens:

        viewer-token -> viewer
        admin-token  -> admin

    Returns None for missing or invalid credentials.
    """

    if authorization_header is None:
        return None

    parts = authorization_header.split(
        " ",
        1,
    )

    if len(parts) != 2:
        return None

    scheme = parts[0]
    token = parts[1]

    if scheme.lower() != "bearer":
        return None

    if not token:
        return None

    return TOKEN_ROLES.get(
        token
    )



def validate_jsonrpc_request(
    payload: Any,
) -> bool:
    """
    Perform basic validation of the JSON-RPC envelope.
    """

    if not isinstance(
        payload,
        dict,
    ):
        return False

    if payload.get(
        "jsonrpc"
    ) != "2.0":
        return False

    method = payload.get(
        "method"
    )

    if not isinstance(
        method,
        str,
    ):
        return False

    if not method:
        return False

    return True




async def forward_to_downstream(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Forward an authorized JSON-RPC request to the
    mock downstream MCP server.

    This function is separate so our tests can verify
    that blocked admin requests never invoke it.
    """

    try:

        async with httpx.AsyncClient(
            timeout=5.0,
        ) as client:

            response = await client.post(
                DOWNSTREAM_URL,
                json=payload,
            )

            response.raise_for_status()

            return response.json()

    except httpx.TimeoutException:

        logger.error(
            "Downstream request timed out"
        )

        raise RuntimeError(
            "Downstream service unavailable"
        )

    except httpx.HTTPError:

        logger.exception(
            "Downstream HTTP request failed"
        )

        raise RuntimeError(
            "Downstream service unavailable"
        )

    except ValueError:

        logger.exception(
            "Downstream returned invalid JSON"
        )

        raise RuntimeError(
            "Downstream service unavailable"
        )



@app.post("/mcp")
async def mcp_gateway(
    request: Request,
):
    """
    Process an incoming JSON-RPC request.

    Flow:

        1. Parse JSON
        2. Validate JSON-RPC envelope
        3. Read Bearer token
        4. Determine role
        5. Inspect tools/call
        6. Block viewer access to admin_* tools
        7. Forward authorized requests downstream
        8. Return downstream response
    """



    try:

        payload = await request.json()

    except Exception:

        logger.warning(
            "Malformed JSON received"
        )

        return JSONResponse(
            status_code=200,
            content=jsonrpc_error(
                None,
                PARSE_ERROR,
                "Parse error",
            ),
        )


  

    if isinstance(
        payload,
        dict,
    ):

        request_id = payload.get(
            "id"
        )

    else:

        request_id = None




    if not validate_jsonrpc_request(
        payload
    ):

        logger.warning(
            "Invalid JSON-RPC request"
        )

        return JSONResponse(
            status_code=200,
            content=jsonrpc_error(
                request_id,
                INVALID_REQUEST,
                "Invalid Request",
            ),
        )


    method = payload[
        "method"
    ]




    authorization_header = (
        request.headers.get(
            "Authorization"
        )
    )

    role = extract_role(
        authorization_header
    )


    if role is None:

        logger.warning(
            "Unauthorized request"
        )

        return JSONResponse(
            status_code=200,
            content=jsonrpc_error(
                request_id,
                UNAUTHORIZED_TOOL_CALL,
                "Unauthorized",
            ),
        )


    logger.info(
        "Authenticated request: role=%s method=%s",
        role,
        method,
    )



    if method == "tools/call":

        params = payload.get(
            "params"
        )


      

        if not isinstance(
            params,
            dict,
        ):

            logger.warning(
                "tools/call missing valid params"
            )

            return JSONResponse(
                status_code=200,
                content=jsonrpc_error(
                    request_id,
                    INVALID_PARAMS,
                    "Invalid params",
                ),
            )


      

        tool_name = params.get(
            "name"
        )


        if (
            not isinstance(
                tool_name,
                str,
            )
            or not tool_name
        ):

            logger.warning(
                "tools/call missing valid tool name"
            )

            return JSONResponse(
                status_code=200,
                content=jsonrpc_error(
                    request_id,
                    INVALID_PARAMS,
                    "Invalid params",
                ),
            )



        if (
            tool_name.startswith(
                "admin_"
            )
            and role != "admin"
        ):

            logger.warning(
                "Blocked unauthorized tool call: "
                "role=%s tool=%s",
                role,
                tool_name,
            )


            return JSONResponse(
                status_code=200,
                content=jsonrpc_error(
                    request_id,
                    UNAUTHORIZED_TOOL_CALL,
                    "Unauthorized Tool Call",
                ),
            )




    try:

        downstream_response = (
            await forward_to_downstream(
                payload
            )
        )

    except RuntimeError:


        return JSONResponse(
            status_code=200,
            content=jsonrpc_error(
                request_id,
                DOWNSTREAM_UNAVAILABLE,
                "Downstream service unavailable",
            ),
        )



    return JSONResponse(
        status_code=200,
        content=downstream_response,
    )



if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "task2.gateway:app",
        host="127.0.0.1",
        port=9000,
        reload=False,
    )
