#!/bin/bash
# CS2 Inventory Manager — 自动备份脚本
# 备份目录：/var/backups/cs2-inventory/
# 保留策略：最近 30 份（每 6 小时一份 = 约 7.5 天）

DB_SRC="/var/www/cs2-inventory-manager/cs2_inventory.db"
BACKUP_DIR="/var/backups/cs2-inventory"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/cs2_inventory_${TIMESTAMP}.db"
KEEP=30

mkdir -p "$BACKUP_DIR"

# SQLite 热备份（不锁表）
sqlite3 "$DB_SRC" ".backup '${BACKUP_FILE}'"

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] 备份成功: ${BACKUP_FILE} (${SIZE})"
    # 删除最旧的，只保留 KEEP 份
    ls -t "${BACKUP_DIR}"/cs2_inventory_*.db 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
    REMAINING=$(ls "${BACKUP_DIR}"/cs2_inventory_*.db 2>/dev/null | wc -l)
    echo "[$(date)] 当前保留备份数: ${REMAINING}"
else
    echo "[$(date)] 备份失败！" >&2
    exit 1
fi
