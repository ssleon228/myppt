#!/bin/sh
# 改动前后对比图：tools/before_after.sh before.pptx after.pptx out.jpg "3 7"（只拼改过的页）
set -e
b="$1"; a="$2"; out="$3"; pages="$4"
t=$(mktemp -d)
cp "$b" "$t/before.pptx"; cp "$a" "$t/after.pptx"
(cd "$t" && soffice --headless --convert-to pdf before.pptx >/dev/null 2>&1 && soffice --headless --convert-to pdf after.pptx >/dev/null 2>&1)
files=""
for p in $pages; do
  pdftoppm -r 50 -png -f "$p" -l "$p" "$t/before.pdf" "$t/b$p"
  pdftoppm -r 50 -png -f "$p" -l "$p" "$t/after.pdf" "$t/a$p"
  files="$files $(ls $t/b$p*.png) $(ls $t/a$p*.png)"
done
montage $files -tile 2x -geometry +8+8 -background '#d9d9d9' "$out"
echo "$out"
