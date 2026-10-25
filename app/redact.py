"""Strip secrets from anything that will be sent to the LLM or stored."""
import re

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GH_TOKEN]"),
    # scheme://user:pass@host
    (re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@]+@"), r"\1[REDACTED]@"),
    # password=..., token: ..., api_key="..."
    (re.compile(r"(?i)\b([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)[\w.-]*)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"),
     r"\1\2[REDACTED]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED_EMAIL]"),
]


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_obj(obj):
    """Redact every string inside a nested structure (keeps JSON valid, unlike redacting the dumped text)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj
