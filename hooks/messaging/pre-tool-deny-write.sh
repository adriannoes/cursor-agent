#!/usr/bin/env bash
# Deny workspace mutation and subagent tools for messaging profile (ADR-001).
set -euo pipefail

input="$(cat)"

extract_tool_name() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r '.tool_name // empty'
    return
  fi
  printf '%s' "$input" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

deny() {
  local reason="$1"
  cat <<EOF
{
  "permission": "deny",
  "user_message": "${reason}",
  "agent_message": "Tool denied in messaging profile (read-only workspace)."
}
EOF
  exit 2
}

tool_name="$(extract_tool_name)"
trimmed="${tool_name#"${tool_name%%[![:space:]]*}"}"
trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"

if [ -z "$trimmed" ]; then
  deny "Missing or empty tool name is not allowed in messaging profile."
fi

tool_lower="$(printf '%s' "$trimmed" | tr '[:upper:]' '[:lower:]')"

case "$tool_lower" in
  write|strreplace|delete|task|edit)
    cat <<EOF
{
  "permission": "deny",
  "user_message": "Messaging profile blocks file edits and subagents.",
  "agent_message": "Tool ${trimmed} is denied in messaging profile (read-only workspace)."
}
EOF
    exit 2
    ;;
  *)
    printf '%s\n' '{"permission": "allow"}'
    exit 0
    ;;
esac
