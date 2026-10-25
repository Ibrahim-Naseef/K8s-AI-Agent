"""Deterministic first pass: find unhealthy pods with plain rules (no LLM needed)."""
from datetime import datetime, timezone

from .k8s_tools import _init, check_ns

WAIT_CATEGORY = {
    "CrashLoopBackOff": "CrashLoopBackOff",
    "ImagePullBackOff": "ImagePullBackOff", "ErrImagePull": "ImagePullBackOff", "InvalidImageName": "ImagePullBackOff",
    "CreateContainerConfigError": "ContainerConfigError", "CreateContainerError": "ContainerConfigError",
    "RunContainerError": "ContainerConfigError",
}


def scan_namespace(ns: str):
    check_ns(ns)
    core, _ = _init()
    now = datetime.now(timezone.utc)
    seen, findings = set(), []

    def add(pod, category, detail):
        if (pod, category) not in seen:
            seen.add((pod, category))
            findings.append({"pod": pod, "category": category, "detail": detail})

    for p in core.list_namespaced_pod(ns).items:
        name, phase = p.metadata.name, p.status.phase
        if phase == "Succeeded" or p.metadata.deletion_timestamp:
            continue
        if phase == "Failed":
            add(name, "Failed/Evicted", p.status.reason or p.status.message)
        if phase == "Pending":
            for c in p.status.conditions or []:
                if c.type == "PodScheduled" and c.status == "False":
                    add(name, "Unschedulable", c.message)
        for cs in (p.status.init_container_statuses or []) + (p.status.container_statuses or []):
            w = cs.state.waiting
            if w and w.reason in WAIT_CATEGORY:
                add(name, WAIT_CATEGORY[w.reason], f"container {cs.name}: {w.reason} {w.message or ''}".strip())
            lt = cs.last_state.terminated if cs.last_state else None
            if lt and lt.reason == "OOMKilled":
                add(name, "OOMKilled", f"container {cs.name} was OOMKilled (restarts={cs.restart_count})")
            age = (now - p.metadata.creation_timestamp).total_seconds()
            if phase == "Running" and cs.state.running and not cs.ready and age > 90:
                add(name, "NotReady", f"container {cs.name} running but not ready for {int(age)}s (probe failing?)")
    return findings
