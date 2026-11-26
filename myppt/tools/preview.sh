#!/bin/sh
# pptx → 每页 PNG + 拼图：tools/preview.sh in.pptx outdir [cols]
set -e
in="$1"; out="$2"; cols="${3:-3}"
mkdir -p "$out"
soffice --headless --convert-to pdf --outdir "$out" "$in" >/dev/null 2>&1
b=$(basename "$in" .pptx)
pdftoppm -r 48 -png "$out/$b.pdf" "$out/$b"
montage "$out/$b"-[0-9]*.png -tile "${cols}x" -geometry +8+8 -background '#d9d9d9' "$out/$b-sheet.jpg"
echo "$out/$b-sheet.jpg"
