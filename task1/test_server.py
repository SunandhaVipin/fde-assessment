import pytest

from mcp import Client, MCPError
from mcp.types import INVALID_PARAMS

from task1.server import server


@pytest.fixture
def anyio_backend():
   
    return "asyncio"


@pytest.fixture
async def client():
    
    async with Client(server) as connected_client:
        yield connected_client


@pytest.mark.anyio
async def test_list_tools(client: Client):
  

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
    

    with pytest.raises(MCPError) as exc:

        await client.call_tool(
            "some_unknown_tool",
            {},
        )

    assert (
        exc.value.error.code
        == INVALID_PARAMS
    )
