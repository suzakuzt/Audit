def test_create_audit_log(client) -> None:
    response = client.post(
        "/api/v1/audit-logs",
        json={
            "actor": "admin",
            "action": "create",
            "resource": "user",
            "detail": "created a new user",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["actor"] == "admin"
    assert data["action"] == "create"
    assert data["resource"] == "user"


def test_create_audit_log_rejects_blank_values(client) -> None:
    response = client.post(
        "/api/v1/audit-logs",
        json={
            "actor": "   ",
            "action": "view",
            "resource": "report",
            "detail": "kept",
        },
    )

    assert response.status_code == 422


def test_list_audit_logs(client) -> None:
    client.post(
        "/api/v1/audit-logs",
        json={
            "actor": "auditor",
            "action": "view",
            "resource": "report",
            "detail": "viewed monthly report",
        },
    )

    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["actor"] == "auditor"
