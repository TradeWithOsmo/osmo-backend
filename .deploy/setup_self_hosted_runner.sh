#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   RUNNER_TOKEN=<token> bash .deploy/setup_self_hosted_runner.sh
#
# Optional env:
#   REPO_URL=https://github.com/TradeWithOsmo/osmo-backend
#   RUNNER_LABELS=tradingapi
#   RUNNER_NAME=tradingapi-1
#   RUNNER_VERSION=2.328.0
#   RUNNER_DIR=/root/actions-runner

REPO_URL="${REPO_URL:-https://github.com/TradeWithOsmo/osmo-backend}"
RUNNER_LABELS="${RUNNER_LABELS:-tradingapi}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)-runner}"
RUNNER_VERSION="${RUNNER_VERSION:-2.328.0}"
RUNNER_DIR="${RUNNER_DIR:-/root/actions-runner}"

if [[ -z "${RUNNER_TOKEN:-}" ]]; then
  echo "ERROR: RUNNER_TOKEN is required."
  echo "Get it from: GitHub Repo -> Settings -> Actions -> Runners -> New self-hosted runner"
  exit 1
fi

echo "[1/6] Preparing runner directory..."
mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

echo "[2/6] Downloading runner v${RUNNER_VERSION}..."
ARCHIVE="actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
curl -fsSL -o "${ARCHIVE}" "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${ARCHIVE}"

echo "[3/6] Extracting runner..."
tar xzf "${ARCHIVE}"

if [[ -f ".runner" ]]; then
  echo "[4/6] Existing runner config found. Removing..."
  ./config.sh remove --token "${RUNNER_TOKEN}" || true
fi

echo "[5/6] Configuring runner..."
./config.sh \
  --url "${REPO_URL}" \
  --token "${RUNNER_TOKEN}" \
  --labels "${RUNNER_LABELS}" \
  --name "${RUNNER_NAME}" \
  --unattended \
  --replace

echo "[6/6] Installing and starting service..."
./svc.sh install
./svc.sh start
./svc.sh status || true

echo "DONE: runner should appear Online in GitHub within a few seconds."
