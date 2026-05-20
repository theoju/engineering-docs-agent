#!/usr/bin/env bash
# Footnote integrity: every [^n] reference must have a matching [^n]: definition,
# and vice versa.
set -euo pipefail

JSON=0
PATHS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON=1; shift ;;
    *) PATHS+=("$1"); shift ;;
  esac
done

results_json=""
any_failed=0

for p in "${PATHS[@]}"; do
  refs=$(grep -oE '\[\^[a-zA-Z0-9_-]+\]' "$p" | grep -v ':' | sort -u || true)
  defs=$(grep -oE '^\[\^[a-zA-Z0-9_-]+\]:' "$p" | sed 's/:$//' | sort -u || true)
  orphan_refs=$(comm -23 <(echo "$refs") <(echo "$defs"))
  orphan_defs=$(comm -13 <(echo "$refs") <(echo "$defs"))

  if [[ -z "$orphan_refs" && -z "$orphan_defs" ]]; then
    ok=true; msg="ok"
  else
    ok=false; any_failed=1
    msg="orphan refs: ${orphan_refs:-none}; orphan defs: ${orphan_defs:-none}"
  fi

  esc_msg=$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
  results_json="${results_json}{\"path\":\"$p\",\"ok\":$ok,\"message\":$esc_msg},"
done

results_json="[${results_json%,}]"
if [[ $JSON -eq 1 ]]; then
  echo "{\"rule\":\"footnotes\",\"severity\":\"block\",\"results\":$results_json}"
fi
exit $any_failed
