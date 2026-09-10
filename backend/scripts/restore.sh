#!/bin/sh
# Restore a pg_dump custom-format backup into a target database.
# Used for the restore drill and for disaster recovery.
#
#   sh backend/scripts/restore.sh BACKUP_FILE TARGET_DATABASE_URL [--yes]
#
# TARGET_DATABASE_URL must be an empty database (the drill creates a fresh
# `specadv_restore` DB). Against anything else the script refuses unless
# --yes is passed explicitly — restoring over production by accident must
# take deliberate effort, not a typo.
set -eu

if [ "$#" -lt 2 ]; then
    echo "usage: restore.sh BACKUP_FILE TARGET_DATABASE_URL [--yes]" >&2
    exit 2
fi
BACKUP_FILE="$1"
TARGET_URL="$2"
CONFIRM="${3:-}"

[ -f "$BACKUP_FILE" ] || { echo "restore: no such file: $BACKUP_FILE" >&2; exit 1; }

case "$TARGET_URL" in
    *specadv_restore*)
        ;;
    *)
        if [ "$CONFIRM" != "--yes" ]; then
            echo "restore: refusing to restore into '$TARGET_URL' without --yes" >&2
            echo "restore: drill target should be an empty specadv_restore database" >&2
            exit 1
        fi
        ;;
esac

command -v pg_restore >/dev/null 2>&1 || { echo "restore: pg_restore not found" >&2; exit 1; }
pg_restore --clean --if-exists --dbname="$TARGET_URL" "$BACKUP_FILE"
echo "restore: done — verify with: psql \"\$TARGET_URL\" -c 'select count(*) from specsession;'"
