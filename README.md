# K8s-AI: AI Kubernetes Troubleshooting Agent

Point it at a namespace. It scans for unhealthy pods with plain rules, then lets an LLM
investigate with **read-only** tools (describe, logs, events, deployments, services, PVCs, nodes)
and returns a root cause, evidence, a suggested fix and a confidence level. History is saved in SQLite.

```
Browser ──► FastAPI (token auth, namespace allowlist)
                │  background job + live progress (polling)
                ▼
        rule-based pre-check ──► LLM tool-calling loop ──► structured diagnosis
                │                      │ (OpenRouter)
                ▼                      ▼
        Kubernetes API (read-only)   redaction layer on everything sent out/stored
```

## What changed from the original HLD

| Original | Here | Why |
|---|---|---|
| Fixed pipeline: collect everything, one LLM call | Agent picks tools step by step (max 8) | Fewer irrelevant tokens; follows the evidence (pod → ConfigMap/PVC/node) |
| LLM only | Rule-based pre-check first | Cheap, deterministic, catches the obvious cases; healthy namespaces cost $0 |
| "Confidence 94%" | low / medium / high **with reasoning** | LLM-reported percentages aren't calibrated |
| Secrets/logs sent as-is | Redaction on all tool output + final answer | Logs routinely contain tokens and DB URLs |
| No auth model for cluster access | Read-only ClusterRole, no Secrets access, namespace allowlist, bearer token (fails closed) | Least privilege |
| Log text trusted | Prompt tells model logs are untrusted data | Prompt-injection via log lines |
| InsForge for auth/DB/realtime/hosting | FastAPI + SQLite + polling | Fewer moving parts. You can swap InsForge back in behind `db.py` |
| No tests | Unit tests + 6 intentionally broken workloads | Ground truth for checking diagnoses |

## What's new

- **Zero manual config for namespaces and token:** all cluster namespaces are auto-discovered (`kube-system`, `kube-public`, `kube-node-lease`, `local-path-storage` hidden). `APP_TOKEN` is optional: empty means no login and localhost-only access. Both `ALLOWED_NAMESPACES` and `APP_TOKEN` still work as optional overrides.
- **All Kubernetes files live in `Kube-files/`** (`rbac.yaml`, `app.yaml`, `errors/`).
- **Error catalog:** 32 reproducible failures (26 files + the original six) in `Kube-files/errors/`, grouped by namespace (below).
- **New UI:** 3D hacker-debugger robot landing page (dark theme, interactive robot, pill menu with Home, How it works, Namespaces, Investigate, Error catalog, History, About, Safety), a **Namespaces** section listing each namespace with its errors (free rule-based scan), and a navbar: Home, Namespaces, History, Investigate.
- **Suggestions are never null:** every diagnosis passes through `app/knowledge.py`. If the model returns an empty or malformed `fix`, a known-good summary, kubectl commands and prevention tips for that error category are filled in. Old history entries are repaired on read.
- The pre-check now also flags stuck `ContainerCreating`, `ReplicaFailure` (quota, missing ServiceAccount) and Services whose selector matches 0 pods. New endpoint: `GET /api/overview`.

## Error catalog (`Kube-files/errors/`)

| Namespace | File | Error |
|---|---|---|
| demo | 01 | Original six: CrashLoop (env), ImagePull, OOMKilled, Unschedulable CPU, Service selector typo, missing Secret |
| err-scheduling | 02-04 | Unschedulable CPU, nodeSelector mismatch, pod anti-affinity |
| err-quota | 05 | ResourceQuota exceeded (FailedCreate) |
| err-config | 06-10 | Missing ConfigMap, wrong Secret key, missing Secret volume (FailedMount), runAsNonRoot vs root image, missing ServiceAccount |
| err-image | 11-14 | Bad tag, private registry (unauthorized), InvalidImageName, unknown registry |
| err-runtime | 15-23 | Exit code 1, command not found, OOMKilled, liveness fails, readiness fails, init container fails, read-only filesystem, RBAC 403, Job BackoffLimitExceeded |
| err-network | 24-26 | Service selector typo, targetPort mismatch, DNS resolution failure |
| err-storage | 27 | PVC Pending (missing StorageClass) |

Not included because kind cannot reproduce them: NetworkPolicy blocks (needs Calico/Cilium), node NotReady/DiskPressure evictions, Ingress without a controller.

## Setup, step by step

### 0. Prerequisites
Docker, kubectl, [kind](https://kind.sigs.k8s.io), Python 3.10+, and a free LLM API key (OpenRouter, Groq or Gemini; see `.env.example`).

### 1. Create a local cluster
```bash
kind create cluster --name doctor
kubectl get nodes
```

### 2. Deploy the broken test workloads (all 32 error scenarios)
```bash
kubectl apply -f Kube-files/errors/      # namespaces first (00-), then every scenario
kubectl get pods -A | grep -E 'demo|err-'   # wait ~2 min; expect CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending, ...
```

### 3. Configure and run the app locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set LLM_API_KEY only (APP_TOKEN and namespaces are optional)
pytest -q                                   # 10 tests should pass
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000 (no login needed locally). Namespaces are discovered automatically; pick one and click **Investigate namespace**.
Locally the app uses your current kubeconfig context.

### 4. Check it diagnoses correctly
| Workload | Expected diagnosis |
|---|---|
| payments (demo) | `DATABASE_URL` env var missing (CrashLoopBackOff) |
| frontend | image tag does not exist (ImagePullBackOff) |
| worker | memory limit 50Mi too low (OOMKilled) |
| batch | requests 100 CPU, no node fits (Unschedulable) |
| web | Service selector `app=webb` matches 0 pods |
| api | Secret `db-credentials` not found (ContainerConfigError) |

The other namespaces follow the table above. Use the question box to focus: "why does the web service have no endpoints?"

### 5. Run it inside the cluster
```bash
docker build -t k8s-ai-agent:0.1.0 .
kind load docker-image k8s-ai-agent:0.1.0 --name doctor     # real clusters: push to your registry and edit Kube-files/app.yaml

kubectl apply -f Kube-files/rbac.yaml
kubectl -n k8s-ai-agent create secret generic k8s-ai-agent-secrets \
  --from-literal=LLM_API_KEY=sk-or-...
# APP_TOKEN is optional; leave it out and use port-forward (localhost-only access)
kubectl apply -f Kube-files/app.yaml
kubectl -n k8s-ai-agent port-forward svc/k8s-ai-agent 8080:80
```
Open http://localhost:8080 (no login with port-forward). If you did set an `APP_TOKEN`, paste it on the page.

### 6. Make it reachable by others (optional)
Put an Ingress with TLS in front of the Service (nginx-ingress + cert-manager), or deploy to any
container host. **Do not expose it without TLS and a strong `APP_TOKEN`.**

## Running on a single EC2 instance (all-free LLM)

**Instance:** Ubuntu 22.04/24.04 with at least 2 vCPU / 4 GB RAM (e.g. t3.medium) and 20 GB disk. A 1 GB micro
instance is too small to run a Kubernetes cluster plus the app. If you only have a small box, install
[k3s](https://k3s.io) instead of kind, or point the app at an existing remote cluster via `~/.kube/config`.

**Security group:** allow only SSH (22) from your IP. Do **not** open port 8000; use an SSH tunnel (below).

```bash
git clone https://github.com/<you>/<repo>.git && cd <repo>
bash scripts/ec2-setup.sh          # Docker, kubectl, kind cluster, demo apps, venv, .env
nano .env                          # set LLM_API_KEY (free key) - keep MODEL=openrouter/free to start
.venv/bin/pytest -q                # optional sanity check
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From **your laptop**:
```bash
ssh -i your-key.pem -L 8000:localhost:8000 ubuntu@<EC2_PUBLIC_IP>
# then open http://localhost:8000 (no login needed)
```

To keep it running after you disconnect, use `deploy/cluster-doctor.service.example` (instructions in its header),
or run uvicorn inside `tmux`.

### Free LLM notes
- `MODEL=openrouter/free` auto-picks a currently-free model that supports tool calling. Quality varies per run and free limits are small (a few investigations per day). Free model lists change often.
- If results are poor or rate-limited, create a free key at Groq or Google AI Studio and use the commented blocks in `.env.example`.
- Free tiers may use your prompts to improve their models. Logs and events are sent to the provider (redacted best-effort), so only investigate non-sensitive workloads on free tiers.

## Hardening checklist before a public deployment
- [ ] TLS everywhere; rotate `APP_TOKEN`; consider real SSO (OIDC proxy such as oauth2-proxy) instead of one shared token
- [ ] Narrow RBAC: replace the ClusterRole with per-namespace `Role`s (the app-level allowlist is not a security boundary on its own)
- [ ] Add rate limiting at the ingress and a spend cap on your OpenRouter key
- [ ] Decide your data policy: logs and events leave your cluster to a third-party LLM (redaction is best-effort, not a guarantee)
- [ ] For multiple replicas, move jobs from memory to a queue/DB and SQLite to Postgres
- [ ] Add NetworkPolicy so the pod can only reach the API server and OpenRouter

## Project layout
```
app/main.py        API, auth, background jobs
app/agent.py       tool-calling loop, system prompt, diagnosis schema
app/k8s_tools.py   read-only tools (+ namespace allowlist, redaction, size caps)
app/precheck.py    rule-based unhealthy-pod scan
app/redact.py      secret scrubbing
app/db.py          SQLite history
app/static/        landing page, namespace overview, investigate, history
app/knowledge.py   known-error catalog + fix fallbacks (no empty suggestions)
Kube-files/         ALL Kubernetes manifests: rbac.yaml, app.yaml, errors/ (32 failure scenarios)
deploy/            systemd unit example (non-Kubernetes)
tests/             redaction, API auth, agent loop (fake LLM)
```

## Ideas for next steps
Add an eval script that runs all six scenarios and scores the diagnoses; stream tokens instead of polling;
add a "Create PR with the fix" step (human-approved); alert-triggered investigations (Alertmanager webhook).
