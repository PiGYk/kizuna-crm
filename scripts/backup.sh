#!/bin/bash
set -e

BACKUP_DIR="/opt/kizuna-crm/backups"
DATE=$(date +%Y-%m-%d_%H-%M)
FILE="$BACKUP_DIR/kizuna_$DATE.sql.gz"
KEEP=7

mkdir -p "$BACKUP_DIR"

# pg_dump всередині контейнера db, стиснути на льоту
docker compose -f /opt/kizuna-crm/docker-compose.yml exec -T db \
  pg_dump -U kizuna kizuna | gzip > "$FILE"

echo "[$(date)] Backup created: $FILE"

# видалити старіші за KEEP останніх
ls -t "$BACKUP_DIR"/kizuna_*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
echo "[$(date)] Old backups cleaned, kept last $KEEP"
