#!/usr/bin/env bash
# inference-emit.sh — bash wrapper around `inference-engine.py emit`.
# Lets plugin hooks emit artifacts without invoking Python directly for trivial cases.
# Not a rewrite of the Python path; delegates to it.
#
# Usage:
#   inference-emit.sh --code F07 --category process-discipline \
#     --title "..." --signal "..." --counter "..." --tags "wixie,lifecycle" [--event-id ID]
#   echo '{"code":"F07",...}' | inference-emit.sh -
#
# Requires: bash, python3 (override with WIXIE_INFERENCE_PYTHON). Respects WIXIE_INFERENCE_ENABLED=1.
#
# Exit status (WIX-RUN-001 emit-lock policy):
#   0  the event is durably recorded: appended to the log ("emitted"), already recorded
#      ("duplicate"), or written to state/pending/ because the state lock stayed busy for
#      WIXIE_INFERENCE_EMIT_WAIT seconds, default 1 ("queued"; folded in exactly once later).
#      The hook running this script needs a timeout > WIXIE_INFERENCE_EMIT_WAIT + 2 s, or Claude
#      Code discards it: keep the default with a 3 s hook timeout, or raise both together.
#      Also 0, silently, when WIXIE_INFERENCE_ENABLED is not 1 (documented no-op).
#   1  the event was NOT recorded (bad flags, missing engine or python, invalid record, engine
#      failure); the reason is on stderr. 1, not 2: Claude Code treats a hook's exit 2 as a
#      blocking error, and a failed emit must not block the tool call that triggered it.

set -uo pipefail

if [ "${WIXIE_INFERENCE_ENABLED:-0}" != "1" ]; then
  exit 0  # silent no-op (brand contract: hooks fail open)
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/inference-engine.py"
PY="${WIXIE_INFERENCE_PYTHON:-python3}"

not_recorded() {
  echo "[inference-emit] event NOT recorded: $*" >&2
  exit 1
}

[ -f "${ENGINE}" ] || not_recorded "engine missing at ${ENGINE}"
command -v "${PY}" >/dev/null 2>&1 || not_recorded "python interpreter '${PY}' not found"

run_engine() {
  "${PY}" -B "${ENGINE}" emit -
  local rc=$?
  [ "${rc}" -eq 0 ] || not_recorded "engine exited ${rc}"
  exit 0
}

# Pipe-in mode: a JSON record on stdin (inherited by the engine).
if [ "${1:-}" = "-" ]; then
  run_engine
fi

# Flag mode: build a JSON record from flags
code=""; category=""; title=""; cause=""; counter=""; signal=""; tags=""; scope=""; event_id=""
while [ $# -gt 0 ]; do
  case "$1" in
    --code|--category|--title|--cause|--counter|--signal|--tags|--scope|--event-id)
      [ $# -ge 2 ] || not_recorded "flag $1 needs a value" ;;
  esac
  case "$1" in
    --code)     code="$2"; shift 2 ;;
    --category) category="$2"; shift 2 ;;
    --title)    title="$2"; shift 2 ;;
    --cause)    cause="$2"; shift 2 ;;
    --counter)  counter="$2"; shift 2 ;;
    --signal)   signal="$2"; shift 2 ;;
    --tags)     tags="$2"; shift 2 ;;    # comma-separated
    --scope)    scope="$2"; shift 2 ;;
    --event-id) event_id="$2"; shift 2 ;;
    *) not_recorded "unknown flag: $1" ;;
  esac
done

if [ -z "${code}" ] || [ -z "${title}" ]; then
  not_recorded "--code and --title are required"
fi

# Build the JSON record with python's json module (handles escaping; no jq dependency).
record=$("${PY}" -c '
import json, sys
code, category, title, cause, counter, signal, scope, tags, event_id = sys.argv[1:10]
rec = {"code": code, "category": category, "title": title, "cause": cause,
       "counter": counter, "signal": signal, "scope": scope,
       "tags": [t for t in tags.split(",")] if tags else []}
if event_id:
    rec["event_id"] = event_id
sys.stdout.write(json.dumps(rec))  # ASCII-escaped: safe on any console code page
' "${code}" "${category}" "${title}" "${cause}" "${counter}" "${signal}" "${scope}" "${tags}" "${event_id}") \
  || not_recorded "could not build the JSON record"

printf '%s' "${record}" | run_engine
exit $?
