#!/bin/bash
# PostgreSQL daily backup script for JARVIS OS
# Runs via cron at 1am daily. Keeps 7 days of backups.
# Logs results to /opt/backups/postgres/backup.log

set -euo pipefail

BACKUP_DIR="/opt/backups/postgres"
DATE=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_FILE="${BACKUP_DIR}/jarvis_${DATE}.sql.gz"
LOG_FILE="${BACKUP_DIR}/backup.log"
RETENTION_DAYS=7

# Postgres container name and credentials (from docker env)
PG_CONTAINER="jarvis-postgres"
PG_USER="${POSTGRES_USER:-jarvis}"
PG_DB="${POSTGRES_DB:-jarvis}"

mkdir -p "$BACKUP_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting backup → ${BACKUP_FILE}"

# Run pg_dump inside the postgres container, pipe through gzip
if docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" "$PG_DB" | gzip > "$BACKUP_FILE"; then
    SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    log "✓ Backup complete — ${SIZE}"
else
    log "✗ Backup FAILED"
    exit 1
fi

# Prune backups older than RETENTION_DAYS
PRUNED=$(find "$BACKUP_DIR" -name "jarvis_*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
if [ "$PRUNED" -gt 0 ]; then
    log "Pruned ${PRUNED} old backup(s)"
fi

# List current backups
CURRENT=$(find "$BACKUP_DIR" -name "jarvis_*.sql.gz" | wc -l)
log "Current backups on disk: ${CURRENT}"
