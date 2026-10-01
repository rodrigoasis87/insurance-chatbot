#!/usr/bin/env bash
# Build the presentation deck (ES + EN) with @marp-team/marp-cli.
# Usage: bash docs/presentation/build_pptx.sh
set -euo pipefail

cd "$(dirname "$0")"

npx -y @marp-team/marp-cli slides_es.md -o slides_es.pptx
npx -y @marp-team/marp-cli slides_en.md -o slides_en.pptx

echo "Built: slides_es.pptx, slides_en.pptx"