#!/usr/bin/env bash
# Shared sensitive-path policy for messaging hook scripts.
# Sourced by shell-gate.sh and read-sensitive-deny.sh from the same directory.

normalize_path() {
  local raw="$1"
  if [ -z "$raw" ]; then
    printf ''
    return
  fi
  case "$raw" in
    "~/"*)
      printf '%s' "${HOME}${raw#\~}"
      ;;
    "~")
      printf '%s' "${HOME}"
      ;;
    *)
      printf '%s' "$raw"
      ;;
  esac
}

is_sensitive_path() {
  local path="$1"
  local base
  base="$(basename "$path")"

  case "$base" in
    .env|.env.*|*.pem|id_rsa|id_rsa.pub|id_ed25519|id_ed25519.pub|known_hosts|authorized_keys|credentials|credentials.json|secrets|secrets.json)
      return 0
      ;;
  esac

  case "$path" in
    */.env|*/.env/*|*/.env.*|*/.ssh|*/.ssh/*|*/.aws/credentials|*/.aws/config)
      return 0
      ;;
  esac

  return 1
}
