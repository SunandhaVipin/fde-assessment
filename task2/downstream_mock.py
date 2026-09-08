import logging
import sys
from typing import Any

import httpx

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ============================================================
# CONFIGURATION
# ============================================================

DOWNSTREAM_URL = (
    "http://127.0.0.1:9001/mcp"
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
    "mcp-gateway"
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="MCP Authorization Gateway",
    version="1.0.0",
)


# ============================================================
# DEMO TOKENS
# ============================================================
#
# For the assessment we use deterministic tokens.
#
# In production these would normally be JWTs or opaque tokens
# validated through an identity provider.
# ============================================================

TOKEN_ROLES = {
    "viewer-token": "viewer",
    "admin-token": "admin",
}


# ============================================================
# JSON-RPC ERROR CODES
# ============================================================

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INVALID_PARAMS = -32602

UNAUTHORIZED_TOOL_CALL = -32001


# ============================================================
# JSON-RPC ERROR HELPER
# ============================================================

def jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
) -> dict[str, Any]:
    """
    Create a JSON-RPC 2.0 error response.
    """

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


# ============================================================
# BEARER TOKEN PARSER
# ============================================================

def extract_role(
    authorization_header: str | None,
) -> str | None:
    """
    Read:

        Authorization: Bearer <token>

    and convert the token into:

        admin

    or:

        viewer

    Invalid or missing credentials return None.
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


# ============================================================
# DOWNSTREAM FORWARDER
# ============================================================

async def forward_to_downstream(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Forward an authorized JSON-RPC request to
    the downstream MCP server.

    This function is deliberately separate so that
    tests can verify that unauthorized requests never
    invoke the downstream service.
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
            "Downstream MCP server timed out"
        )

        raise RuntimeError(
            "Downstream service unavailable"
        )


    except httpx.HTTPError:

        logger.exception(
            "Downstream MCP communication failed"
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


# ============================================================
# VALIDATE JSON-RPC ENVELOPE
# ============================================================

def validate_jsonrpc_request(
    payload: Any,
) -> bool:
    """
    Perform basic JSON-RPC envelope validation.
    """

    if not isinstance(
        payload,
        dict,
    ):
        return False


    if payload.get("jsonrpc") != "2.0":
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


# ============================================================
# MCP GATEWAY ENDPOINT
# ============================================================

@app.post("/mcp")
async def mcp_gateway(
    request: Request,
):
    """
    Main gateway endpoint.

    Flow:

        request
            ↓
        parse JSON
            ↓
        validate JSON-RPC
            ↓
        authenticate Bearer token
            ↓
        inspect tools/call
            ↓
        enforce admin_* authorization
            ↓
        forward authorized request
            ↓
        return downstream response
    """


    # ========================================================
    # STEP 1: PARSE JSON
    # ========================================================

    try:

        payload = await request.json()

    except Exception:

        logger.warning(
            "Request contained invalid JSON"
        )

        return JSONResponse(
            status_code=200,
            content=jsonrpc_error(
                None,
                PARSE_ERROR,
                "Parse error",
            ),
        )


    # ========================================================
    # STEP 2: VALIDATE JSON-RPC ENVELOPE
    # ========================================================

    request_id = (
        payload.get("id")
        if isinstance(payload, dict)
        else None
    )


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


    method = payload["method"]


    # ========================================================
    # STEP 3: AUTHENTICATE
    # ========================================================

    authorization = request.headers.get(
        "Authorization"
    )


    role = extract_role(
        authorization
    )


    if role is None:

        logger.warning(
            "Request rejected due to invalid credentials"
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
        "Authenticated request role=%s method=%s",
        role,
        method,
    )


    # ========================================================
    # STEP 4: AUTHORIZE tools/call
    # ========================================================

    if method == "tools/call":

        params = payload.get(
            "params"
        )


        # ----------------------------------------------------
        # Validate tools/call params
        # ----------------------------------------------------

        if not isinstance(
            params,
            dict,
        ):

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


        if not isinstance(
            tool_name,
            str,
        ) or not tool_name:

            return JSONResponse(
                status_code=200,
                content=jsonrpc_error(
                    request_id,
                    INVALID_PARAMS,
                    "Invalid params",
                ),
            )


        # ----------------------------------------------------
        # SECURITY POLICY
        #
        # Any tool beginning with:
        #
        #     admin_
        #
        # requires:
        #
        #     role == "admin"
        # ----------------------------------------------------

        if (
            tool_name.startswith(
                "admin_"
            )
            and role != "admin"
        ):

            logger.warning(
                "Blocked unauthorized tool call "
                "role=%s tool=%s",
                role,
                tool_name,
            )


            # IMPORTANT:
            #
            # We return here BEFORE calling:
            #
            # forward_to_downstream(...)
            #
            # Therefore unauthorized calls cannot reach
            # the protected downstream tool.

            return JSONResponse(
                status_code=200,
                content=jsonrpc_error(
                    request_id,
                    UNAUTHORIZED_TOOL_CALL,
                    "Unauthorized Tool Call",
                ),
            )


    # ========================================================
    # STEP 5: FORWARD AUTHORIZED REQUEST
    # ========================================================

    try:

        downstream_response = (
            await forward_to_downstream(
                payload
            )
        )


    except RuntimeError:

        # Do not leak internal networking exceptions,
        # URLs, stack traces, etc. to the client.

        return JSONResponse(
            status_code=200,
            content=jsonrpc_error(
                request_id,
                -32000,
                "Downstream service unavailable",
            ),
        )


    # ========================================================
    # STEP 6: RETURN DOWNSTREAM RESPONSE TRANSPARENTLY
    # ========================================================

    return JSONResponse(
        status_code=200,
        content=downstream_response,
    )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "task2.gateway:app",
        host="127.0.0.1",
        port=9000,
        reload=False,
    )