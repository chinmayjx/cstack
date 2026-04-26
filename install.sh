#!/usr/bin/env bash
# cstack install helper.
# Claude Code's plugin commands are slash commands and cannot be invoked from
# the shell, so this script only does pre-flight checks and prints the exact
# slash commands you need to run inside a Claude Code session.

set -euo pipefail

CSTACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "cstack install helper"
echo "====================="
echo

# 1. claude CLI present?
if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: 'claude' command not found on PATH." >&2
  echo "Install Claude Code first: https://claude.com/claude-code" >&2
  exit 1
fi
echo "✓ claude CLI found at: $(command -v claude)"

# 2. Marketplace manifest valid?
MARKETPLACE_JSON="$CSTACK_DIR/.claude-plugin/marketplace.json"
if [[ ! -f "$MARKETPLACE_JSON" ]]; then
  echo "ERROR: $MARKETPLACE_JSON is missing." >&2
  exit 1
fi
if command -v jq >/dev/null 2>&1; then
  if ! jq empty "$MARKETPLACE_JSON" >/dev/null 2>&1; then
    echo "ERROR: $MARKETPLACE_JSON is not valid JSON." >&2
    exit 1
  fi
  MARKETPLACE_NAME="$(jq -r '.name' "$MARKETPLACE_JSON")"
  PLUGIN_COUNT="$(jq -r '.plugins | length' "$MARKETPLACE_JSON")"
  echo "✓ marketplace.json valid; name = $MARKETPLACE_NAME; plugins listed = $PLUGIN_COUNT"
else
  echo "(skipping JSON validation — install jq for stricter checks)"
fi

# 3. List discoverable plugins
echo
if command -v jq >/dev/null 2>&1; then
  if [[ "$PLUGIN_COUNT" == "0" ]]; then
    echo "No plugins are currently declared in marketplace.json."
    echo "Add one under plugins/ and register it in marketplace.json before installing."
  else
    echo "Plugins declared in marketplace.json:"
    jq -r '.plugins[] | "  - \(.name): \(.description)"' "$MARKETPLACE_JSON"
  fi
else
  echo "Plugins declared in marketplace.json (raw):"
  grep -E '"name":|"description":' "$MARKETPLACE_JSON" | sed 's/^/  /'
fi

# 4. Print next-step slash commands
cat <<EOF

Next steps — run these inside a Claude Code session:

  /plugin marketplace add $CSTACK_DIR

Then install whichever plugin you want from the marketplace:

  /plugin install <plugin-name>@cstack

Verify with the plugin's own skill:

  /<plugin-name>:<skill-name>
EOF
