#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

./scripts/setup-stack.sh --no-up --no-bootstrap --no-connections --no-wait --set USER_ID="${USER_ID:-1000}" --set GROUP_ID="${GROUP_ID:-1000}"
