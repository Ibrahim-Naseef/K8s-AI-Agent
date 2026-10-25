"""Deterministic first pass: find unhealthy pods with plain rules (no LLM needed)."""
from datetime import datetime, timezone

from .k8s_tools import _init, check_ns

WAIT_CATEGORY = {
    "CrashLoopBackOff": "CrashLoopBackOff",
    "ImagePullBackOff": "ImagePullBackOff", "ErrImagePull": "ImagePullBackOff", "InvalidImageName": "ImagePullBackOff",
    "CreateContainerConfigError": "ContainerConfigError", "CreateContainerError": "ContainerConfigError",
    "RunContainerError": "ContainerConfigError",
}
STUCK_AFTER = 60  # seconds in ContainerCreating before we flag it


def scan_namespace(ns: str):
    check_ns(ns)
    core, apps = _init()
    now = datetime.now(timezone.utc)
    seen, findings = set(), []

    def add(pod, category, detail):
        if (pod, category) not in seen:
            seen.add((pod, category))
            findings.append({"pod": pod, "category": category, "detail": detail})

    pods = core.list_namespaced_pod(ns).items
    for p in pods:
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
            if w and w.reason == "ContainerCreating" and (now - p.metadata.creation_timestamp).total_seconds() > STUCK_AFTER:
                add(name, "StuckCreating", f"container {cs.name} still ContainerCreating (volume/secret/configmap mount?)")
            lt = cs.last_state.terminated if cs.last_state else None
            if lt and lt.reason == "OOMKilled":
                add(name, "OOMKilled", f"container {cs.name} was OOMKilled (restarts={cs.restart_count})")
            age = (now - p.metadata.creation_timestamp).total_seconds()
            if phase == "Running" and cs.state.running and not cs.ready and age > 90:
                add(name, "NotReady", f"container {cs.name} running but not ready for {int(age)}s (probe failing?)")
    for d in apps.list_namespaced_deployment(ns).items:  # pods that could not even be created
        for c in d.status.conditions or []:
            if c.type == "ReplicaFailure" and c.status == "True":
                add(d.metadata.name, "ReplicaFailure", c.message)
    for svc in core.list_namespaced_service(ns).items:  # Service with selector but zero matching pods
        sel = svc.spec.selector or {}
        if sel and not any(all((p.metadata.labels or {}).get(k) == v for k, v in sel.items()) for p in pods):
            add(svc.metadata.name, "ServiceSelectorMismatch", f"Service selector {sel} matches 0 pods")
    return findings
