#!/usr/bin/env bash
# Run one command inside witness-ctl (private Lima home of this repo), working directory /opt/witness-lab.
# Remediation helper for logged one-off checks; scripts/lab_vms.sh remains the normal entry point.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export LIMA_HOME="${WIT_LIMA_HOME:-$REPO/.lima.nosync}"
exec limactl shell --workdir /opt/witness-lab witness-ctl -- "$@"
