#!/bin/bash
set -euo pipefail
exec /bin/bash "$(dirname "$0")/RUN_ON_THIS_MAC.sh" --return
