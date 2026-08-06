#!/usr/bin/env bash
# Regenerates architecture.svg from architecture.mmd.
set -euo pipefail
cd "$(dirname "$0")"

npx -y -p @mermaid-js/mermaid-cli -p mermaid mmdc \
    -i architecture.mmd -o architecture.svg -c mermaid.json -b white
