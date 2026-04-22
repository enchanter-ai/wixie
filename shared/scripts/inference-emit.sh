#!/usr/bin/env bash
# inference-emit.sh — bash wrapper around `inference-engine.py emit`.
# Lets plugin hooks emit artifacts without invoking Python directly for trivial cases.
# Not a rewrite of the Python path; delegates to it.
#
# Usage:
#   inference-emit.sh --code F07 --category process-discipline \
#     --title "..." --signal "..." --counter "..." --tags "flux,lifecycle"
#   echo '{"code":"F07",...}' | inference-emit.sh -
#
# Requires: bash, jq, python3. Respects FLUX_INFERENCE_ENABLED=1.

set -uo pipefail

if [ "${FLUX_INFERENCE_ENABLED:-0}" != "1" ]; then
  exit 0  # silent no-op (brand contract: hooks fail open)
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/inference-engine.py"

if [ ! -f "${ENGINE}" ]; then
  echo "[inference-emit] engine missing at ${ENGINE}" >&2
  exit 0  # fail open
fi

# Pipe-in mode: a JSON record on stdin
if [ "${1:-}" = "-" ]; then
  python3 "${ENGINE}" emit - < /dev/stdin
  exit $?
fi

# Flag mode: build a JSON record from flags
code=""; category=""; title=""; cause=""; counter=""; signal=""; tags=""; scope=""
while [ $# -gt 0 ]; do
  case "$1" in
    --code)     code="$2"; shift 2 ;;
    --category) category="$2"; shift 2 ;;
    --title)    title="$2"; shift 2 ;;
    --cause)    cause="$2"; shift 2 ;;
    --counter)  counter="$2"; shift 2 ;;
    --signal)   signal="$2"; shift 2 ;;
    --tags)     tags="$2"; shift 2 ;;    # comma-separated
    --scope)    scope="$2"; shift 2 ;;
    *) echo "[inference-emit] unknown flag: $1" >&2; exit 0 ;;
  esac
done

if [ -z "${code}" ] || [ -z "${title}" ]; then
  echo "[inference-emit] --code and --title are required" >&2
  exit 0
fi

# Build the JSON record via jq (handles escaping).
record=$(jq -cn \
  --arg code "${code}" \
  --arg category "${category}" \
  --arg title "${title}" \
  --arg cause "${cause}" \
  --arg counter "${counter}" \
  --arg signal "${signal}" \
  --arg scope "${scope}" \
  --arg tags "${tags}" \
  '{
    code: $code,
    category: $category,
    title: $title,
    cause: $cause,
    counter: $counter,
    signal: $signal,
    scope: $scope,
    tags: (if $tags == "" then [] else ($tags | split(",")) end)
  }')

echo "${record}" | python3 "${ENGINE}" emit -
