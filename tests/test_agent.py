"""Run the agent loop with a scripted fake LLM and a fake cluster."""
import json
from types import SimpleNamespace as NS

from app import agent


def _call(id, name, args):
    return NS(id=id, function=NS(name=name, arguments=json.dumps(args)))


class FakeMsg:
    def __init__(self, calls, content=None):
        self.tool_calls = calls
        self.content = content

    def model_dump(self, exclude_none=True):
        return {"role": "assistant", "content": self.content,
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in self.tool_calls]}


class FakeLLM:
    def __init__(self, script):
        self.script = iter(script)
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        item = next(self.script)
        msg = FakeMsg([], item) if isinstance(item, str) else FakeMsg(item)
        return NS(choices=[NS(message=msg)])


def test_loop_runs_tools_then_submits(monkeypatch):
    monkeypatch.setattr(agent, "scan_namespace", lambda ns: [{"pod": "payments-1", "category": "CrashLoopBackOff", "detail": "x"}])
    ran = []
    monkeypatch.setattr(agent, "run_tool", lambda n, a: ran.append(n) or '{"logs":"FATAL: DATABASE_URL is not set"}')
    diag = {"root_cause": "DATABASE_URL missing password=hunter2", "category": "ConfigError", "evidence": ["log"],
            "fix": {"summary": "add env"}, "confidence": {"level": "high", "reasoning": "log says so"}}
    llm = FakeLLM([[_call("1", "get_pod_logs", {"namespace": "demo", "name": "payments-1", "previous": True})],
                   [_call("2", "submit_diagnosis", diag)]])
    monkeypatch.setattr(agent, "_client", lambda: llm)
    events = []
    out = agent.investigate("demo", "", lambda k, m, d=None: events.append((k, m)))
    assert ran == ["get_pod_logs"]
    assert out["category"] == "ConfigError"
    assert "hunter2" not in out["root_cause"]          # output is redacted
    assert any(k == "tool" for k, _ in events)


def test_healthy_namespace_skips_llm(monkeypatch):
    monkeypatch.setattr(agent, "scan_namespace", lambda ns: [])
    monkeypatch.setattr(agent, "_client", lambda: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    out = agent.investigate("demo", "", lambda *a, **k: None)
    assert out["category"] == "Healthy"


def test_text_json_answer_is_accepted(monkeypatch):
    monkeypatch.setattr(agent, "scan_namespace", lambda ns: [{"pod": "p", "category": "OOMKilled", "detail": ""}])
    llm = FakeLLM(['Here you go: {"root_cause": "memory limit too low", "category": "OOMKilled"}'])
    monkeypatch.setattr(agent, "_client", lambda: llm)
    out = agent.investigate("demo", "", lambda *a, **k: None)
    assert out["root_cause"] == "memory limit too low"
    assert out["confidence"]["level"] == "low"      # defaults filled in
