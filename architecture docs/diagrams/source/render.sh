#!/usr/bin/env bash
# Render every SVG in ../ to PNG with headless Chrome (same pixel size as the SVG).
set -euo pipefail
cd "$(dirname "$0")/.."
for f in *.svg; do
  w=$(grep -o 'width="[0-9]*"' "$f" | head -1 | tr -dc 0-9); h=$(grep -o 'height="[0-9]*"' "$f" | head -1 | tr -dc 0-9)
  google-chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars --force-device-scale-factor=1 \
    --screenshot="${f%.svg}.png" --window-size="${w},${h}" "file://$PWD/$f" >/dev/null 2>&1
  echo "rendered ${f%.svg}.png (${w}x${h})"
done
