#!/bin/sh
# Nightly Postgres backup for the single-VM deploy.
#
# Usage (cron on the VM, or `docker compose -f docker-compose.prod.yml exec`):
#   DATABASE_URL=postgresql://specadv:PASSWORD@db:5432/specadv \
#   BACKUP_DIR=/var/backups/specadversary \
#   RETENTION_DAYS=14 \
#   sh backend/scripts/backup.sh
#
# Produces BACKUP_DIR/specadv-YYYYmmddHHMMSS.dump (pg_dump custom format)
# and deletes dumps older than RETENTION_DAYS. Offsite copy (rsync/S3) is
# the operator's cron step after this script succeeds — a backup that never
# leaves the VM is not a backup.
set -eu

: "${DATABASE_URL:?DATABASE_URL must be set}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/specadversary}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

command -v pg_dump >/dev/null 2>&1 || { echo "backup: pg_dump not found" >&2; exit 1; }
command -v pg_isready >/dev/null 2>&1 || { echo "backup: pg_isready not found" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"

# Fail fast when the database is unreachable rather than writing an
# empty dump that looks like a backup.
pg_isready -d "$DATABASE_URL" >/dev/null || { echo "backup: database unreachable" >&2; exit 1; }

STAMP="$(date -u +%Y%m%d%H%M%S)"
OUT="$BACKUP_DIR/specadv-$STAMP.dump"
pg_dump --format=custom --file="$OUT" --dbname="$DATABASE_URL"
echo "backup: wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Retention: prune dumps older than RETENTION_DAYS. The just-written dump
# is minutes old, so it always survives this pass.
find "$BACKUP_DIR" -maxdepth 1 -name 'specadv-*.dump' -mtime +"$RETENTION_DAYS" -print | while IFS= read -r f; do
    rm -f "$f" && echo "backup: pruned $f"
done

echo "backup: done"
