#!/usr/bin/env bash
# One-shot setup for Ubuntu 22.04/24.04 EC2 (x86_64 or arm64/Graviton).
# Installs Docker, kubectl, kind, creates a local cluster, deploys the demo broken apps,
# creates a Python venv and a .env.
# Run from the repo root:  bash scripts/ec2-setup.sh
set -euo pipefail

[ -f app/main.py ] || { echo "Run this from the repo root (where app/ lives)."; exit 1; }

case "$(uname -m)" in
  x86_64)  ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
  *) echo "Unsupported CPU: $(uname -m)"; exit 1 ;;
esac

echo "==> Installing OS packages + Docker"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git openssl python3 python3-venv python3-pip docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

if ! command -v kubectl >/dev/null; then
  echo "==> Installing kubectl"
  KVER="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
  curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/${KVER}/bin/linux/${ARCH}/kubectl"
  sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
fi

if ! command -v kind >/dev/null; then
  echo "==> Installing kind"
  curl -fsSLo /tmp/kind "https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-${ARCH}"
  sudo install -m 0755 /tmp/kind /usr/local/bin/kind
fi

# 'sg docker' lets us use the docker group right now, without logging out and back in.
if ! sg docker -c "kind get clusters" 2>/dev/null | grep -qx doctor; then
  echo "==> Creating kind cluster 'doctor' (takes ~1-2 min)"
  sg docker -c "kind create cluster --name doctor"
fi

echo "==> Deploying intentionally broken demo workloads"
kubectl apply -f Kube-files/errors/

echo "==> Python environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env (APP_TOKEN left empty: the app accepts localhost connections only)"
fi

cat <<MSG

Done. Remaining manual steps:
  1. Put your free LLM key in .env  ->  nano .env   (set LLM_API_KEY=...)
  2. Run tests (optional):           .venv/bin/pytest -q
  3. Start the app:                  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
  4. From YOUR laptop, open a tunnel: ssh -i <key.pem> -L 8000:localhost:8000 ubuntu@<EC2_PUBLIC_IP>
     then browse http://localhost:8000 (no login needed).
MSG
