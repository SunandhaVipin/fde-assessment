import pytest

from mcp import Client, MCPError
from mcp.types import INVALID_PARAMS

from task1.server import server


@pytest.fixture
def anyio_backend():
    """
    Force pytest-anyio to use asyncio.
    """
    return "asyncio"


@pytest.fixture
async def client():
    """
    Create an in-memory MCP client connected directly
    to the Task 1 server.
    """
    async with Client(server) as connected_client:
        yield connected_client


@pytest.mark.anyio
async def test_list_tools(client: Client):
    """
    Verify that both required MCP tools are advertised.
    """

    result = await client.list_tools()

    tool_names = [
        tool.name
        for tool in result.tools
    ]

    assert tool_names == [
        "get_customer_record",
        "trigger_refund",
    ]


@pytest.mark.anyio
async def test_customer_tool_schema(client: Client):
    """
    Verify that get_customer_record advertises
    customer_id as a required input.
    """

    result = await client.list_tools()

    customer_tool = next(
        tool
        for tool in result.tools
        if tool.name == "get_customer_record"
    )

    schema = customer_tool.input_schema

    assert "customer_id" in schema["properties"]
    assert "customer_id" in schema["required"]


@pytest.mark.anyio
async def test_refund_tool_schema(client: Client):
    """
    Verify that trigger_refund advertises all
    required inputs.
    """

    result = await client.list_tools()

    refund_tool = next(
        tool
        for tool in result.tools
        if tool.name == "trigger_refund"
    )

    schema = refund_tool.input_schema

    assert "customer_id" in schema["properties"]
    assert "amount" in schema["properties"]
    assert "reason" in schema["properties"]

    assert "customer_id" in schema["required"]
    assert "amount" in schema["required"]
    assert "reason" in schema["required"]


@pytest.mark.anyio
async def test_get_customer_record_success(
    client: Client,
):
    """
    Valid customer ID should return customer data.
    """

    result = await client.call_tool(
        "get_customer_record",
        {
            "customer_id": "CUST-12345"
        },
    )

    assert result.is_error is not True

    assert (
        result.structured_content["customer_id"]
        == "CUST-12345"
    )

    assert (
        result.structured_content["name"]
        == "Alice Johnson"
    )

    assert (
        result.structured_content["status"]
        == "active"
    )


@pytest.mark.anyio
async def test_second_customer_success(
    client: Client,
):
    """
    Verify the second mock customer can also
    be retrieved successfully.
    """

    result = await client.call_tool(
        "get_customer_record",
        {
            "customer_id": "CUST-54321"
        },
    )

    assert result.is_error is not True

    assert (
        result.structured_content["customer_id"]
        == "CUST-54321"
    )

    assert (
        result.structured_content["name"]
        == "Bob Smith"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "customer_id",
    [
        "12345",
        "CUST-1234",
        "CUST-123456",
        "cust-12345",
        "Cust-12345",
        "CUST-ABCDE",
        "",
    ],
)
async def test_invalid_customer_id_format(
    client: Client,
    customer_id,
):
    """
    Invalid customer ID formats must generate
    JSON-RPC Invalid Params (-32602).
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "get_customer_record",
            {
                "customer_id": customer_id
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_missing_customer_id(
    client: Client,
):
    """
    Missing customer_id should be rejected.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "get_customer_record",
            {},
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_extra_customer_fields_rejected(
    client: Client,
):
    """
    Unexpected arguments should be rejected
    because extra='forbid' is enabled.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "get_customer_record",
            {
                "customer_id": "CUST-12345",
                "unexpected": "value",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_nonexistent_customer_is_tool_error(
    client: Client,
):
    """
    CUST-99999 has the correct format, so this
    should be a tool execution error rather than
    an Invalid Params error.
    """

    result = await client.call_tool(
        "get_customer_record",
        {
            "customer_id": "CUST-99999"
        },
    )

    assert result.is_error is True

    assert (
        "not found"
        in result.content[0].text.lower()
    )


@pytest.mark.anyio
async def test_trigger_refund_success(
    client: Client,
):
    """
    A valid refund request should succeed.
    """

    result = await client.call_tool(
        "trigger_refund",
        {
            "customer_id": "CUST-12345",
            "amount": 50.0,
            "reason": "Duplicate transaction detected",
        },
    )

    assert result.is_error is not True

    assert (
        result.structured_content["status"]
        == "accepted"
    )

    assert (
        result.structured_content["customer_id"]
        == "CUST-12345"
    )

    assert (
        result.structured_content["amount"]
        == 50.0
    )

    assert (
        result.structured_content["reason"]
        == "Duplicate transaction detected"
    )


@pytest.mark.anyio
async def test_zero_refund_rejected(
    client: Client,
):
    """
    Refund amount must be greater than zero.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "amount": 0.0,
                "reason": "Duplicate transaction detected",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_negative_refund_rejected(
    client: Client,
):
    """
    Negative refund amounts must be rejected.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "amount": -25.0,
                "reason": "Duplicate transaction detected",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_short_refund_reason_rejected(
    client: Client,
):
    """
    Refund reason must contain at least
    10 characters.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "amount": 25.0,
                "reason": "Too short",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_missing_refund_reason_rejected(
    client: Client,
):
    """
    Missing refund reason should fail validation.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "amount": 25.0,
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_missing_refund_amount_rejected(
    client: Client,
):
    """
    Missing amount should fail validation.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "reason": "Duplicate transaction detected",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_invalid_refund_customer_id(
    client: Client,
):
    """
    Refunds should enforce the same CUST-XXXXX
    customer ID format.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "12345",
                "amount": 25.0,
                "reason": "Duplicate transaction detected",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_extra_refund_field_rejected(
    client: Client,
):
    """
    Unexpected fields must not be silently ignored.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "amount": 25.0,
                "reason": "Duplicate transaction detected",
                "approved_by": "attacker",
            },
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )


@pytest.mark.anyio
async def test_refund_for_nonexistent_customer(
    client: Client,
):
    """
    Valid customer ID format but missing customer
    should produce a tool execution error.
    """

    result = await client.call_tool(
        "trigger_refund",
        {
            "customer_id": "CUST-99999",
            "amount": 25.0,
            "reason": "Duplicate transaction detected",
        },
    )

    assert result.is_error is True

    assert (
        "not found"
        in result.content[0].text.lower()
    )


@pytest.mark.anyio
async def test_unknown_tool(
    client: Client,
):
    """
    Unknown tool names are rejected by our
    dispatcher.
    """

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "some_unknown_tool",
            {},
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )