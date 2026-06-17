#!/usr/bin/env bash
# Deny all MCP execution for messaging profile (defense in depth with empty MCP config).
set -euo pipefail

cat >/dev/null

cat <<'EOF'
{
  "permission": "deny",
  "user_message": "MCP tools are disabled in messaging profile.",
  "agent_message": "MCP execution is denied for messaging (mcp_servers must be empty)."
}
EOF
exit 2
