def test_health_check(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "批量核心字段提取验证器" in response.text

