#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# The Replit preview runs the React UI; keep its locked dependencies current
# after merged UI changes. The native desktop shell is not part of this workflow.
npm ci --prefix "$repo_root/ui" --no-audit --no-fund