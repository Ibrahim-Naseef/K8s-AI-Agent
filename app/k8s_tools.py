"""Read-only Kubernetes tools the agent can call. No tool ever reads Secrets or mutates anything."""
import json
import time
from datetime import datetime, timezone

from kubernetes import client, config as kconfig
from kubernetes.client.exceptions import ApiException

from . import config
from .redact import redact, redact_obj

_core = None
_apps = None
MAX_TOOL_CHARS = 6000


def _init():
    global _core, _apps
    if _core is None:
        try:
            kconfig.load_incluster_config()
        except kconfig.ConfigException:
            kconfig.load_kube_config()
        _core, _apps = client.CoreV1Api(), client.AppsV1Api()
    return _core, _apps


_NS_CACHE = {"t": 0.0, "v": []}


def list_namespaces() -> list:
    """Explicit ALLOWED_NAMESPACES if set, otherwise every cluster namespace minus system ones (cached 10s)."""
    if config.ALLOWED_NAMESPACES:
        return list(config.ALLOWED_NAMESPACES)
    if _NS_CACHE["v"] and time.time() - _NS_CACHE["t"] < 10:
        return list(_NS_CACHE["v"])
    core, _ = _init()
    names = sorted(n.metadata.name for n in core.list_namespace().items
                   if n.metadata.name not in config.EXCLUDE_NAMESPACES)
    _NS_CACHE.update(t=time.time(), v=names)
    return names


def check_ns(ns: str):
    allowed = list_namespaces()
    if ns not in allowed:
        raise PermissionError(f"namespace '{ns}' is not allowed (known: {allowed})")


def _probe(p):
    if not p:
        return None
    out = {"period": p.period_seconds, "failure_threshold": p.failure_threshold}
    if p.http_get:
        out.update(type="http", path=p.http_get.path, port=str(p.http_get.port))
    elif p.tcp_socket:
        out.update(type="tcp", port=str(p.tcp_socket.port))
    elif p._exec:
        out.update(type="exec")
    return out


def _cstatus(cs):
    if cs is None:
        return None
    s = cs.state
    out = {"ready": cs.ready, "restarts": cs.restart_count}
    if s.waiting:
        out.update(state="waiting", reason=s.waiting.reason, message=s.waiting.message)
    elif s.terminated:
        out.update(state="terminated", reason=s.terminated.reason, exit_code=s.terminated.exit_code)
    elif s.running:
        out.update(state="running", started_at=str(s.running.started_at))
    lt = cs.last_state.terminated if cs.last_state else None
    if lt:
        out["last_terminated"] = {"reason": lt.reason, "exit_code": lt.exit_code, "finished_at": str(lt.finished_at)}
    return out


# ---------------------------------------------------------------- tools
def list_pods(namespace: str, label_selector: str = ""):
    check_ns(namespace)
    core, _ = _init()
    pods = core.list_namespaced_pod(namespace, label_selector=label_selector or None).items
    out = []
    for p in pods:
        cs = p.status.container_statuses or []
        out.append({
            "name": p.metadata.name, "phase": p.status.phase,
            "ready": f"{sum(1 for c in cs if c.ready)}/{len(p.spec.containers)}",
            "restarts": sum(c.restart_count for c in cs),
            "node": p.spec.node_name, "labels": p.metadata.labels,
        })
    return out


def describe_pod(namespace: str, name: str):
    check_ns(namespace)
    core, _ = _init()
    p = core.read_namespaced_pod(name, namespace)
    statuses = {c.name: c for c in (p.status.container_statuses or []) + (p.status.init_container_statuses or [])}
    containers = []
    for c in p.spec.containers + (p.spec.init_containers or []):
        env = []
        for e in c.env or []:
            if e.value_from and e.value_from.secret_key_ref:
                src = f"secret:{e.value_from.secret_key_ref.name}/{e.value_from.secret_key_ref.key}"
            elif e.value_from and e.value_from.config_map_key_ref:
                src = f"configmap:{e.value_from.config_map_key_ref.name}/{e.value_from.config_map_key_ref.key}"
            elif e.value_from:
                src = "fieldRef/other"
            else:
                src = "literal"  # value intentionally NOT included
            env.append({"name": e.name, "source": src})
        for ef in c.env_from or []:
            ref = ef.secret_ref or ef.config_map_ref
            env.append({"envFrom": ("secret:" if ef.secret_ref else "configmap:") + (ref.name if ref else "?")})
        containers.append({
            "name": c.name, "image": c.image, "command": c.command, "args": c.args,
            "ports": [x.container_port for x in c.ports or []],
            "resources": {"requests": c.resources.requests, "limits": c.resources.limits},
            "env": env,
            "readiness_probe": _probe(c.readiness_probe), "liveness_probe": _probe(c.liveness_probe),
            "status": _cstatus(statuses.get(c.name)),
        })
    return {
        "name": name, "phase": p.status.phase, "reason": p.status.reason, "node": p.spec.node_name,
        "node_selector": p.spec.node_selector,
        "conditions": [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                       for c in p.status.conditions or []],
        "containers": containers,
        "volumes": [v.name for v in p.spec.volumes or []],
        "owner": [(o.kind, o.name) for o in p.metadata.owner_references or []],
    }


def get_pod_logs(namespace: str, name: str, container: str = "", previous: bool = False, tail_lines: int = 0):
    check_ns(namespace)
    core, _ = _init()
    tail = min(tail_lines or config.LOG_TAIL_LINES, 300)
    try:
        logs = core.read_namespaced_pod_log(name, namespace, container=container or None,
                                            previous=previous, tail_lines=tail)
    except ApiException as e:
        return {"error": f"{e.status} {e.reason}", "hint": "try previous=true for crashed containers"}
    return {"logs": redact(logs)[-MAX_TOOL_CHARS:]}


def get_events(namespace: str, object_name: str = ""):
    check_ns(namespace)
    core, _ = _init()
    fs = f"involvedObject.name={object_name}" if object_name else None
    evs = core.list_namespaced_event(namespace, field_selector=fs).items
    evs.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp
             or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [{"type": e.type, "reason": e.reason, "object": f"{e.involved_object.kind}/{e.involved_object.name}",
             "message": e.message, "count": e.count} for e in evs[:20]]


def get_deployment(namespace: str, name: str):
    check_ns(namespace)
    _, apps = _init()
    d = apps.read_namespaced_deployment(name, namespace)
    s = d.status
    return {
        "name": name, "desired": d.spec.replicas, "ready": s.ready_replicas or 0,
        "updated": s.updated_replicas or 0, "available": s.available_replicas or 0,
        "unavailable": s.unavailable_replicas or 0,
        "strategy": d.spec.strategy.type,
        "selector": d.spec.selector.match_labels,
        "pod_template_labels": d.spec.template.metadata.labels,
        "images": [c.image for c in d.spec.template.spec.containers],
        "conditions": [{"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                       for c in s.conditions or []],
    }


def get_service(namespace: str, name: str):
    check_ns(namespace)
    core, _ = _init()
    svc = core.read_namespaced_service(name, namespace)
    sel = svc.spec.selector or {}
    matching = []
    if sel:
        matching = core.list_namespaced_pod(namespace, label_selector=",".join(f"{k}={v}" for k, v in sel.items())).items
    try:
        ep = core.read_namespaced_endpoints(name, namespace)
        ready = sum(len(s.addresses or []) for s in ep.subsets or [])
        not_ready = sum(len(s.not_ready_addresses or []) for s in ep.subsets or [])
    except ApiException:
        ready = not_ready = 0
    out = {
        "name": name, "type": svc.spec.type, "selector": sel,
        "ports": [{"port": p.port, "target_port": str(p.target_port), "protocol": p.protocol} for p in svc.spec.ports or []],
        "matching_pods": [p.metadata.name for p in matching],
        "endpoints_ready": ready, "endpoints_not_ready": not_ready,
    }
    if sel and not matching:
        labels = {json.dumps(p.metadata.labels, sort_keys=True) for p in core.list_namespaced_pod(namespace).items}
        out["warning"] = "selector matches 0 pods"
        out["labels_present_in_namespace"] = [json.loads(x) for x in list(labels)[:10]]
    return out


def get_pvc(namespace: str, name: str):
    check_ns(namespace)
    core, _ = _init()
    p = core.read_namespaced_persistent_volume_claim(name, namespace)
    return {"name": name, "phase": p.status.phase, "storage_class": p.spec.storage_class_name,
            "requested": p.spec.resources.requests, "volume": p.spec.volume_name}


def list_nodes():
    core, _ = _init()
    out = []
    for n in core.list_node().items:
        out.append({
            "name": n.metadata.name,
            "conditions": {c.type: c.status for c in n.status.conditions or []},
            "allocatable": n.status.allocatable,
            "taints": [f"{t.key}={t.value}:{t.effect}" for t in n.spec.taints or []],
        })
    return out


TOOLS = {
    "list_pods": list_pods, "describe_pod": describe_pod, "get_pod_logs": get_pod_logs,
    "get_events": get_events, "get_deployment": get_deployment, "get_service": get_service,
    "get_pvc": get_pvc, "list_nodes": list_nodes,
}


def run_tool(name: str, args: dict) -> str:
    """Execute a tool; always returns a redacted, size-capped JSON string (never raises)."""
    fn = TOOLS.get(name)
    if not fn:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        result = fn(**args)
    except ApiException as e:
        result = {"error": f"kubernetes API {e.status}: {e.reason}"}
    except (PermissionError, TypeError) as e:
        result = {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    return json.dumps(redact_obj(json.loads(json.dumps(result, default=str))))[:MAX_TOOL_CHARS]
