#!/bin/bash
# Forza il percorso di node e claude-flow
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# Lancia il server deviando TUTTO lo sporco su un log file per debug
/opt/homebrew/bin/claude-flow mcp start --quiet > /tmp/mcp-stdout.log 2> /tmp/mcp-stderr.log