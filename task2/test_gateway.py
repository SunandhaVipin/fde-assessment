import pytest

from fastapi.testclient import TestClient

from task2 import gateway




client = TestClient(
    gateway.app
)



def test_viewer_token_extracts_viewer_role():

    role = gateway.extract_role(
        "Bearer viewer-token"
    )

    assert role == "viewer"


def test_admin_token_extracts_admin_role():

    role = gateway.extract_role(
        "Bearer admin-token"
    )

    assert role == "admin"


def test_invalid_token_returns_none():

    role = gateway.extract_role(
        "Bearer invalid-token"
    )

    assert role is None


def test_missing_authorization_returns_none():

    role = gateway.extract_role(
        None
    )

    assert role is None




def test_tools_list_forwarded_for_viewer(
    monkeypatch,
):

    downstream_called = False


    async def fake_forward(
        payload,
    ):

        nonlocal downstream_called

        downstream_called = True

        assert (
            payload["method"]
            == "tools/list"
        )

        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "tools": [
                    {
                        "name": "get_profile"
                    },
                    {
                        "name": "admin_reset_key"
                    },
                ]
            },
        }


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        },
    )


    body = response.json()


    assert response.status_code == 200

    assert downstream_called is True

    assert body["id"] == 1

    assert (
        body["result"]["tools"][0]["name"]
        == "get_profile"
    )



def test_viewer_can_call_normal_tool(
    monkeypatch,
):

    downstream_called = False


    async def fake_forward(
        payload,
    ):

        nonlocal downstream_called

        downstream_called = True

        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "Profile retrieved",
                    }
                ],
                "isError": False,
            },
        }


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_profile",
                "arguments": {
                    "customer_id":
                        "CUST-12345",
                },
            },
        },
    )


    body = response.json()


    assert response.status_code == 200

    assert downstream_called is True

    assert "result" in body

    assert (
        body["result"]["isError"]
        is False
    )




def test_viewer_admin_tool_blocked_before_downstream(
    monkeypatch,
):

    downstream_called = False


    async def fake_forward(
        payload,
    ):

        nonlocal downstream_called

        downstream_called = True

        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {},
        }


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "admin_reset_key",
                "arguments": {
                    "customer_id":
                        "CUST-12345",
                },
            },
        },
    )


    body = response.json()


    assert response.status_code == 200


  

    assert downstream_called is False


    assert "error" in body

    assert (
        body["error"]["code"]
        == -32001
    )

    assert (
        body["error"]["message"]
        == "Unauthorized Tool Call"
    )




def test_admin_can_call_admin_tool(
    monkeypatch,
):

    downstream_called = False


    async def fake_forward(
        payload,
    ):

        nonlocal downstream_called

        downstream_called = True

        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "API key reset",
                    }
                ],
                "isError": False,
            },
        }


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer admin-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name":
                    "admin_reset_key",
                "arguments": {
                    "customer_id":
                        "CUST-12345",
                },
            },
        },
    )


    body = response.json()


    assert response.status_code == 200

    assert downstream_called is True

    assert "result" in body

    assert (
        body["result"]["isError"]
        is False
    )



def test_missing_token_rejected(
    monkeypatch,
):

    downstream_called = False


    async def fake_forward(
        payload,
    ):

        nonlocal downstream_called

        downstream_called = True

        return {}


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/list",
        },
    )


    body = response.json()


    assert response.status_code == 200

    assert downstream_called is False

    assert (
        body["error"]["code"]
        == -32001
    )

    assert (
        body["error"]["message"]
        == "Unauthorized"
    )




def test_invalid_token_rejected(
    monkeypatch,
):

    downstream_called = False


    async def fake_forward(
        payload,
    ):

        nonlocal downstream_called

        downstream_called = True

        return {}


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer fake-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/list",
        },
    )


    body = response.json()


    assert downstream_called is False

    assert (
        body["error"]["code"]
        == -32001
    )




def test_tools_call_missing_name():

    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {},
        },
    )


    body = response.json()


    assert (
        body["error"]["code"]
        == -32602
    )




def test_invalid_jsonrpc_request():

    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token"
        },
        json={
            "jsonrpc": "1.0",
            "id": 8,
            "method": "tools/list",
        },
    )


    body = response.json()


    assert (
        body["error"]["code"]
        == -32600
    )




def test_malformed_json():

    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token",
            "Content-Type":
                "application/json",
        },
        content="{this is not valid json",
    )


    body = response.json()


    assert (
        body["error"]["code"]
        == -32700
    )





def test_downstream_failure_is_sanitized(
    monkeypatch,
):

    async def fake_forward(
        payload,
    ):

        raise RuntimeError(
            "secret internal failure"
        )


    monkeypatch.setattr(
        gateway,
        "forward_to_downstream",
        fake_forward,
    )


    response = client.post(
        "/mcp",
        headers={
            "Authorization":
                "Bearer viewer-token"
        },
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/list",
        },
    )


    body = response.json()


    assert (
        body["error"]["code"]
        == -32000
    )

    assert (
        body["error"]["message"]
        == "Downstream service unavailable"
    )

    assert (
        "secret"
        not in str(body)
    )
