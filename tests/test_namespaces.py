from types import SimpleNamespace as NS

import pytest

from app import config, k8s_tools


class FakeCore:
    def list_namespace(self):
        names = ["default", "kube-system", "kube-public", "demo", "err-runtime", "local-path-storage"]
        return NS(items=[NS(metadata=NS(name=n)) for n in names])


def test_namespaces_are_auto_discovered(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_NAMESPACES", [])
    monkeypatch.setattr(k8s_tools, "_init", lambda: (FakeCore(), None))
    k8s_tools._NS_CACHE.update(t=0.0, v=[])
    try:
        assert k8s_tools.list_namespaces() == ["default", "demo", "err-runtime"]
        k8s_tools.check_ns("err-runtime")
        with pytest.raises(PermissionError):
            k8s_tools.check_ns("kube-system")
    finally:
        k8s_tools._NS_CACHE.update(t=0.0, v=[])
