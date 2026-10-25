
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import k8s_tools  # noqa: E402

H = {"Authorization": "Bearer test-token"}


def test_requires_token():
    with TestClient(app) as c:
        assert c.get("/api/namespaces").status_code == 401
        assert c.get("/api/namespaces", headers=H).json() == ["demo"]


def test_namespace_allowlist():
    with TestClient(app) as c:
        r = c.post("/api/investigations", headers=H, json={"namespace": "kube-system", "question": ""})
        assert r.status_code == 403


def test_tool_refuses_other_namespace():
    out = k8s_tools.run_tool("list_pods", {"namespace": "kube-system"})
    assert "not allowed" in out


def _from(host):
    """Wrap the app so requests appear to come from `host`."""
    async def wrapper(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, 5000)}
        await app(scope, receive, send)
    return wrapper


def test_no_token_means_localhost_only(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "APP_TOKEN", "")
    with TestClient(_from("127.0.0.1")) as c:
        assert c.get("/api/config").json() == {"auth_required": False}
        assert c.get("/api/namespaces").status_code == 200
    with TestClient(_from("10.1.2.3")) as c:
        assert c.get("/api/namespaces").status_code == 403
