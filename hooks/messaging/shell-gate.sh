#!/usr/bin/env bash
# Allow read-only shell commands; deny destructive or exfiltration-prone commands.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=sensitive-paths.sh
source "${SCRIPT_DIR}/sensitive-paths.sh"

input="$(cat)"

extract_command() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r '.command // empty'
    return
  fi
  printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

deny() {
  local reason="$1"
  cat <<EOF
{
  "permission": "deny",
  "user_message": "${reason}",
  "agent_message": "Shell command denied by messaging allowlist: ${reason}"
}
EOF
  exit 2
}

allow() {
  printf '%s\n' '{"permission": "allow"}'
  exit 0
}

last_path_argument() {
  local cmd="$1"
  local last=""
  local word
  for word in $cmd; do
    case "$word" in
      -*) continue ;;
      cat|head|tail|file|stat|wc|echo|printf|test|true|false)
        continue
        ;;
      *)
        last="$word"
        ;;
    esac
  done
  printf '%s' "$last"
}

deny_if_sensitive_path_token() {
  local token="$1"
  local path="$1"

  case "$token" in
    *:*)
      path="${token#*:}"
      ;;
  esac

  path="$(normalize_path "$path")"
  if [ -n "$path" ] && is_sensitive_path "$path"; then
    deny "Sensitive file reads via shell are blocked in messaging profile."
  fi
}

deny_if_sensitive_read_target() {
  local cmd="$1"
  case "$cmd" in
    cat\ *|head\ *|tail\ *|file\ *|stat\ *)
      deny_if_sensitive_path_token "$(last_path_argument "$cmd")"
      ;;
  esac
}

deny_if_unsafe_grep_rg() {
  local cmd="$1"
  local tool=""
  case "$cmd" in
    grep\ *) tool="grep" ;;
    rg\ *) tool="rg" ;;
    *) return 0 ;;
  esac

  local word
  for word in $cmd; do
    case "$word" in
      -r|-R|--recursive|--hidden)
        deny "Recursive grep/rg is blocked in messaging profile."
        ;;
    esac
  done

  local seen_pattern=0
  local path_count=0
  for word in $cmd; do
    case "$word" in
      "$tool") continue ;;
      -*) continue ;;
      *)
        if [ "$seen_pattern" -eq 0 ]; then
          seen_pattern=1
          continue
        fi
        path_count=$((path_count + 1))
        case "$word" in
          .|./|..|../*|*'*'*|*'?'*)
            deny "grep/rg requires an explicit safe path in messaging profile."
            ;;
        esac
        deny_if_sensitive_path_token "$word"
        ;;
    esac
  done

  if [ "$path_count" -eq 0 ]; then
    deny "grep/rg requires an explicit safe path in messaging profile."
  fi
}

command="$(extract_command)"
trimmed="${command#"${command%%[![:space:]]*}"}"
trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"

if [ -z "$trimmed" ]; then
  deny "Empty shell command is not allowed in messaging profile."
fi

# Deny chaining, substitution, redirection, and background operators.
case "$trimmed" in
  *";"*|*"&&"*|*"||"*|*"|"*|*'$('*|*'`'*|*'${'*|*'$'*)
    deny "Shell chaining or substitution is blocked in messaging profile."
    ;;
  *"|"*sh|*"|"*bash|*"|"*zsh|*"|"*/bin/sh|*"|"*/bin/bash)
    deny "Pipe-to-shell patterns are blocked in messaging profile."
    ;;
  *" > "*|*">>"*|*" < "*|*"&"*)
    deny "Shell redirection or background execution is blocked in messaging profile."
    ;;
esac

case "$trimmed" in
  rm*|rmdir*|mv*|cp*|chmod*|chown*|sudo*|kill*|pkill*|killall*|dd*|mkfs*|truncate*)
    deny "Destructive shell command blocked in messaging profile."
    ;;
  curl*|wget*|nc*|netcat*|ncat*|ssh*|scp*|sftp*|ftp*|telnet*|nmap*)
    deny "Network or remote shell tools are blocked in messaging profile."
    ;;
  git\ push*|git\ commit*|git\ reset*|git\ checkout\ *|git\ restore*|git\ clean*|git\ rebase*)
    deny "Mutating git commands are blocked in messaging profile."
    ;;
  git\ show|git\ show\ *|git\ diff|git\ diff\ *|git\ log|git\ log\ *)
    deny "git history inspection is blocked in messaging profile."
    ;;
  find\ *)
    deny "find is not allowed in messaging profile."
    ;;
esac

deny_if_sensitive_read_target "$trimmed"
deny_if_unsafe_grep_rg "$trimmed"

# Allowlist read-only commands used for code Q&A.
case "$trimmed" in
  git\ status|git\ status\ *|git\ branch|git\ branch\ *|git\ rev-parse|git\ rev-parse\ *)
    allow
    ;;
  ls|ls\ *|pwd|pwd\ *|cat\ *|head\ *|tail\ *|wc\ *|file\ *|stat\ *|tree|tree\ *)
    allow
    ;;
  grep\ *|rg\ *|echo\ *|printf\ *|test\ *|true|false)
    allow
    ;;
esac

deny "Command is not on the messaging read-only allowlist."
