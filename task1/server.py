import asyncio
import json
import logging
import sys
from typing import Annotated, Any

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


# stdout belongs to MCP stdio. Application logs go only to stderr.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("customer-mcp")


# ---------------------------------------------------------
# Strict validation types
# ---------------------------------------------------------

CustomerId = Annotated[
    str,
    StringConstraints(
        pattern=r"^CUST-\d{5}$",
        strip_whitespace=True,
    ),
]

RefundReason = Annotated[
    str,
    StringConstraints(
        min_length=10,
        strip_whitespace=True,
    ),
]


class GetCustomerRecordInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    customer_id: CustomerId


class TriggerRefundInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    customer_id: CustomerId
    amount: float = Field(gt=0)
    reason: RefundReason


# ---------------------------------------------------------
# Mock customer data
# ---------------------------------------------------------

CUSTOMERS: dict[str, dict[str, Any]] = {
    "CUST-12345": {
        "customer_id": "CUST-12345",
        "name": "Alice Johnson",
        "email": "alice@example.com",
        "status": "active",
    },
    "CUST-54321": {
        "customer_id": "CUST-54321",
        "name": "Bob Smith",
        "email": "bob@example.com",
        "status": "active",
    },
}


# ---------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------

GET_CUSTOMER_TOOL = Tool(
    name="get_customer_record",
    description="Retrieve a customer record using a CUST-XXXXX identifier.",
    input_schema=GetCustomerRecordInput.model_json_schema(),
)


TRIGGER_REFUND_TOOL = Tool(
    name="trigger_refund",
    description="Trigger a positive-value refund for a customer.",
    input_schema=TriggerRefundInput.model_json_schema(),
)


# ---------------------------------------------------------
# tools/list
# ---------------------------------------------------------

async def list_tools(
    ctx: ServerRequestContext,
    params: PaginatedRequestParams | None,
) -> ListToolsResult:

    logger.info("tools/list requested")

    return ListToolsResult(
        tools=[
            GET_CUSTOMER_TOOL,
            TRIGGER_REFUND_TOOL,
        ]
    )


# ---------------------------------------------------------
# Validation error helper
# ---------------------------------------------------------

def invalid_arguments(exc: ValidationError) -> MCPError:
    """
    Convert Pydantic validation errors into
    JSON-RPC Invalid Params (-32602).
    """

    return MCPError(
        INVALID_PARAMS,
        "Invalid tool arguments",
        data={
            "validation_errors": exc.errors(
                include_input=False,
                include_url=False,
                include_context=False,
            )
        },
    )


# ---------------------------------------------------------
# tools/call
# ---------------------------------------------------------

async def call_tool(
    ctx: ServerRequestContext,
    params: CallToolRequestParams,
) -> CallToolResult:

    arguments = params.arguments or {}

    logger.info(
        "tools/call requested tool=%s",
        params.name,
    )

    # -----------------------------------------------------
    # Tool 1: get_customer_record
    # -----------------------------------------------------

    if params.name == "get_customer_record":

        try:
            validated = GetCustomerRecordInput.model_validate(
                arguments
            )

        except ValidationError as exc:
            raise invalid_arguments(exc)

        customer = CUSTOMERS.get(
            validated.customer_id
        )

        # Valid request, but business operation failed.
        if customer is None:

            return CallToolResult(
                is_error=True,
                content=[
                    TextContent(
                        type="text",
                        text=(
                            f"Customer "
                            f"{validated.customer_id} "
                            f"was not found."
                        ),
                    )
                ],
            )

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(customer),
                )
            ],
            structured_content=customer,
        )

    # -----------------------------------------------------
    # Tool 2: trigger_refund
    # -----------------------------------------------------

    if params.name == "trigger_refund":

        try:
            validated = TriggerRefundInput.model_validate(
                arguments
            )

        except ValidationError as exc:
            raise invalid_arguments(exc)

        if validated.customer_id not in CUSTOMERS:

            return CallToolResult(
                is_error=True,
                content=[
                    TextContent(
                        type="text",
                        text=(
                            f"Customer "
                            f"{validated.customer_id} "
                            f"was not found."
                        ),
                    )
                ],
            )

        result = {
            "status": "accepted",
            "customer_id": validated.customer_id,
            "amount": validated.amount,
            "reason": validated.reason,
        }

        logger.info(
            "refund accepted customer=%s amount=%.2f",
            validated.customer_id,
            validated.amount,
        )

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(result),
                )
            ],
            structured_content=result,
        )

    # -----------------------------------------------------
    # Unknown tool
    # -----------------------------------------------------

    raise MCPError(
        INVALID_PARAMS,
        f"Unknown tool: {params.name}",
    )


# ---------------------------------------------------------
# Create MCP Server
# ---------------------------------------------------------

server = Server(
    "customer-service",
    version="1.0.0",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


# ---------------------------------------------------------
# STDIO transport
# ---------------------------------------------------------

async def main() -> None:

    logger.info(
        "starting customer MCP server"
    )

    async with stdio_server() as (
        read_stream,
        write_stream,
    ):

        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())