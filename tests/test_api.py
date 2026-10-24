import json

from starlette.testclient import TestClient

from ninety.api import app as api


def test_health_reports_the_commit(monkeypatch):
    monkeypatch.setattr(api, "COMMIT", "abc1234")
    response = TestClient(api.app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "commit": "abc1234"}


def test_unknown_routes_and_methods_are_refused():
    client = TestClient(api.app)
    assert client.get("/api/nope").status_code == 404
    assert client.post("/api/health").status_code == 405


MCP = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def call(key_configured: str, sent: str | None, body=LIST):
    with TestClient(api.build(key_configured)) as client:
        headers = MCP | ({"x-api-key": sent} if sent is not None else {})
        return client.post("/mcp", json=body, headers=headers)


def test_mcp_needs_the_key():
    assert call("k" * 64, None).status_code == 401
    assert call("k" * 64, "wrong").status_code == 401


def test_mcp_without_a_configured_key_refuses_everyone():
    # Fail closed: a missing Key Vault reference must not open the endpoint.
    assert call("", "").status_code == 503
    assert call("", "anything").status_code == 503


def test_mcp_with_the_key_lists_the_match_tools():
    response = call("k" * 64, "k" * 64)
    assert response.status_code == 200
    names = sorted(t["name"] for t in response.json()["result"]["tools"])
    assert names == ["list_events", "match_info", "re_perceive", "team_shape"]


def test_mcp_answers_a_tool_call():
    body = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "match_info", "arguments": {"match": "seed7"}},
    }
    result = call("k" * 64, "k" * 64, body).json()["result"]
    assert result["isError"] is False and json.loads(result["content"][0]["text"])["minutes"] == 5
