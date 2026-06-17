#!/usr/bin/env bash
# Deny reads of sensitive paths (.env, SSH keys, PEM) for messaging profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=sensitive-paths.sh
source "${SCRIPT_DIR}/sensitive-paths.sh"

input="$(cat)"

extract_file_path() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r '.file_path // empty'
    return
  fi
  printf '%s' "$input" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

file_path="$(normalize_path "$(extract_file_path)")"

if [ -z "$file_path" ]; then
  cat <<EOF
{
  "permission": "deny",
  "user_message": "Messaging profile blocks reads when the requested path is unavailable."
}
EOF
  exit 2
fi

if is_sensitive_path "$file_path"; then
  cat <<EOF
{
  "permission": "deny",
  "user_message": "Messaging profile blocks reads of sensitive files."
}
EOF
  exit 2
fi

printf '%s\n' '{"permission": "allow"}'
exit 0
