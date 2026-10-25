
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
