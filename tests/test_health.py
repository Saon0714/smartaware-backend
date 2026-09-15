from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]


def test_cors_is_not_a_wildcard(client: TestClient) -> None:
    """A wildcard origin would break credentialed auth and is never acceptable."""
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_health_reports_whether_the_schema_is_current(client: TestClient) -> None:
    """A database left behind a migration answers every page that touches a
    changed table with a 500 and nothing else. Being able to ask turns that
    into a question with an answer."""
    body = client.get("/api/v1/health").json()
    assert body["schema_status"] == "ok"
    assert body["schema_applied"] == body["schema_expected"]
    assert body["schema_expected"]


def test_a_stale_schema_is_reported_as_such(client: TestClient, monkeypatch) -> None:
    from app.db import schema_version

    monkeypatch.setattr(
        schema_version,
        "read",
        lambda: schema_version.SchemaVersion(applied="older", expected="newer"),
    )
    body = client.get("/api/v1/health").json()
    assert body["schema_status"] == "stale"
    assert (body["schema_applied"], body["schema_expected"]) == ("older", "newer")
