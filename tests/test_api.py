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
