#!/usr/bin/env bash
# Backup do PostgreSQL via pg_dump, rodando dentro do container `db`.
#
# Uso:
#   ./scripts/backup_db.sh
#   make backup
#
# Agendamento recomendado (crontab do host, backup diário às 3h):
#   0 3 * * * cd /caminho/do/projeto && ./scripts/backup_db.sh >> backups/backup.log 2>&1
#
# Restauração:
#   gunzip -c backups/whatsapp_langchain_2026-07-31_0300.sql.gz | \
#       docker compose exec -T db psql -U postgres whatsapp_langchain

set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backups"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date +%F_%H%M)"
FILENAME="whatsapp_langchain_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "Gerando backup: ${BACKUP_DIR}/${FILENAME}"
docker compose exec -T db pg_dump -U postgres whatsapp_langchain | gzip > "${BACKUP_DIR}/${FILENAME}"

echo "Removendo backups com mais de ${RETENTION_DAYS} dias..."
find "$BACKUP_DIR" -name "whatsapp_langchain_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete

echo "Backup concluído: ${FILENAME}"
