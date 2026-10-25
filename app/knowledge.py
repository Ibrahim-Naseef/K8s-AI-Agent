"""Known Kubernetes failure modes: fallback fixes so a diagnosis never shows an empty suggestion."""
_D = "kubectl -n {ns} describe pod {pod}"
_L = "kubectl -n {ns} logs {pod} --previous"
_E = "kubectl -n {ns} get events --sort-by=.lastTimestamp"
CATALOG = {
    "CrashLoopBackOff": ("The container starts and exits. Read the previous logs, fix the missing config or bug, then roll out again.",
        [_L, _D], ["Add startup validation and clear error messages", "Use readiness probes and staged rollouts"]),
    "ImagePullBackOff": ("The image cannot be pulled. Check the tag, registry host and pull credentials.",
        [_D, "kubectl -n {ns} get deploy -o wide", "kubectl -n {ns} set image deploy/<name> <container>=<registry/image:valid-tag>"],
        ["Pin immutable tags or digests", "Use imagePullSecrets for private registries"]),
    "ContainerConfigError": ("A referenced Secret, ConfigMap, key or security setting is missing or invalid. Create it or correct the reference.",
        [_D, "kubectl -n {ns} get secret,configmap,serviceaccount"], ["Deploy config objects before workloads", "Validate manifests in CI (kubeconform)"]),
    "ConfigError": ("A referenced Secret, ConfigMap, key or env var is missing. Create it or correct the reference.",
        [_D, "kubectl -n {ns} get secret,configmap"], ["Deploy config objects before workloads"]),
    "OOMKilled": ("The container exceeded its memory limit. Raise the limit or fix the leak.",
        [_D, "kubectl -n {ns} top pod {pod}", "kubectl -n {ns} set resources deploy/<name> --limits=memory=256Mi"],
        ["Size limits from real usage", "Alert on memory near the limit"]),
    "Unschedulable": ("No node satisfies the pod's requests, selectors, affinity, taints or volumes. Relax the constraint or add capacity.",
        [_D, "kubectl describe nodes", "kubectl get nodes --show-labels"], ["Right-size requests", "Review nodeSelector, affinity and tolerations"]),
    "ResourceExhaustion": ("Cluster, node or namespace resources are exhausted. Free capacity or raise quota.",
        ["kubectl -n {ns} describe resourcequota", "kubectl describe nodes"], ["Set quotas and alerts"]),
    "ReplicaFailure": ("The ReplicaSet cannot create pods (quota exceeded or ServiceAccount missing). Fix the cause named in the event.",
        [_E, "kubectl -n {ns} describe resourcequota", "kubectl -n {ns} get serviceaccount"], ["Create ServiceAccounts first", "Monitor quota usage"]),
    "ServiceSelectorMismatch": ("The Service selector matches no pods, so it has no endpoints. Align the selector with the pod labels.",
        ["kubectl -n {ns} get svc,endpoints", "kubectl -n {ns} get pods --show-labels"], ["Use consistent label conventions", "Test Services after each deploy"]),
    "ProbeFailure": ("A liveness or readiness probe fails. Check the path, port and startup time of the probe.",
        [_D, _E], ["Add a startupProbe for slow apps", "Test probe endpoints locally"]),
    "NotReady": ("The container runs but never becomes Ready. Check the readiness probe and the app's health endpoint.",
        [_D, _E], ["Add a startupProbe for slow apps"]),
    "DNS/Network": ("Name resolution or connectivity fails. Verify the target Service name, namespace, CoreDNS and NetworkPolicies.",
        ["kubectl -n kube-system get pods -l k8s-app=kube-dns", "kubectl -n {ns} get networkpolicy,svc"], ["Use fully qualified service names", "Review NetworkPolicies"]),
    "Storage": ("A PersistentVolumeClaim is Pending or a volume cannot mount. Check the StorageClass and volume events.",
        ["kubectl -n {ns} get pvc", "kubectl get storageclass", _E], ["Use a default StorageClass", "Check provisioner health"]),
    "StuckCreating": ("The pod is stuck in ContainerCreating, usually a missing volume, Secret or ConfigMap mount. Check events.",
        [_D, _E], ["Create mounted objects before the workload"]),
    "RolloutFailure": ("The rollout is not progressing. Inspect the new ReplicaSet's pods and roll back if needed.",
        ["kubectl -n {ns} rollout status deploy/<name>", "kubectl -n {ns} rollout undo deploy/<name>"], ["Use progressDeadlineSeconds and readiness probes"]),
    "Failed/Evicted": ("The pod failed or was evicted, often from node pressure. Check the reason and node conditions.",
        [_D, "kubectl describe nodes"], ["Set requests and limits so pods are not evicted first"]),
    "Healthy": ("Nothing to fix.", [], []),
    "Other": ("Inspect events, describe the failing object and read the logs for the first error.", [_D, _E, _L], ["Add alerts on restarts and pending pods"]),
}


def _lst(v):
    if isinstance(v, str):
        v = [v]
    return [x.strip() for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []


def normalize(d, ns="<namespace>", pod=None):
    """Make any model output safe to render: fix is always a dict with a real summary and commands."""
    d = dict(d) if isinstance(d, dict) else {}
    cat = d.get("category") if d.get("category") in CATALOG else "Other"
    d["category"] = cat
    summary, cmds, prev = CATALOG[cat]
    d["affected"], d["evidence"] = _lst(d.get("affected")), _lst(d.get("evidence"))
    if not isinstance(d.get("root_cause"), str) or not d["root_cause"].strip():
        d["root_cause"] = "The model did not state a root cause; see evidence."
    fix = d.get("fix")
    fix = {"summary": fix} if isinstance(fix, str) else dict(fix) if isinstance(fix, dict) else {}
    s = fix.get("summary")
    if not isinstance(s, str) or s.strip().lower() in ("", "null", "none", "n/a"):
        s = summary
    pod = pod or (d["affected"][0] if d["affected"] else "<pod>")
    fix["summary"] = s.strip()
    fix["commands"] = _lst(fix.get("commands")) or [c.format(ns=ns, pod=pod) for c in cmds]
    y = fix.get("yaml_snippet")
    fix["yaml_snippet"] = y if isinstance(y, str) and y.strip().lower() not in ("null", "none") else ""
    d["fix"] = fix
    d["prevention"] = _lst(d.get("prevention")) or prev
    c = d.get("confidence")
    d["confidence"] = c if isinstance(c, dict) and c.get("level") in ("low", "medium", "high") else \
        {"level": "low", "reasoning": "Model gave no confidence."}
    d["confidence"].setdefault("reasoning", "")
    return d
