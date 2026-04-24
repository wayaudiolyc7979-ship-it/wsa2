#!/bin/bash
# WSA2 수동 백업 스크립트
# 사용법: ./backup_wsa2.sh  또는  bash backup_wsa2.sh

SRC="/Users/yuncheollee/WSA2/wayaudo2.py"
BDIR="/Users/yuncheollee/WSA2/backups"
mkdir -p "$BDIR"

TS=$(date "+%Y%m%d_%H%M%S")
DEST="$BDIR/wayaudo2_${TS}.py"
cp "$SRC" "$DEST"
cp "$SRC" "/Users/yuncheollee/WSA2/wayaudo2.backup.py"

# 최근 20개만 유지
ls -t "$BDIR"/wayaudo2_*.py 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null

echo "[$(date '+%H:%M:%S')] 백업 저장: $DEST ($(wc -l < "$SRC") 줄)"
