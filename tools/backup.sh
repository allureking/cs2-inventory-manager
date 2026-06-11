#!/bin/bash
# CS2 Inventory Manager — 自动备份脚本 (v0.13: VACUUM INTO + gzip 瘦身)
# 备份目录：/var/backups/cs2-inventory/
# 保留策略：最近 30 份（每 6 小时一份 = 约 7.5 天）
#
# v0.13 变更(提案4):旧版 .backup 会复制空闲页(489MB 库 71% 是空页),
# 改用 VACUUM INTO 只写实际数据(~140MB),再 gzip(~40MB)。
# 恢复:gunzip 后即为完整可用的 sqlite 库(恢复演练已验证,见 CHANGELOG v0.13.0)。

DB_SRC="/var/www/cs2-inventory-manager/cs2_inventory.db"
BACKUP_DIR="/var/backups/cs2-inventory"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/cs2_inventory_${TIMESTAMP}.db"
KEEP=30

mkdir -p "$BACKUP_DIR"

# VACUUM INTO：原子地写出紧凑副本（只含实际数据页，不长时间锁源库）
sqlite3 "$DB_SRC" "VACUUM INTO '${BACKUP_FILE}'"

if [ $? -eq 0 ]; then
    gzip -f "$BACKUP_FILE"
    SIZE=$(du -sh "${BACKUP_FILE}.gz" | cut -f1)
    echo "[$(date)] 备份成功: ${BACKUP_FILE}.gz (${SIZE})"
    # 删除最旧的，只保留 KEEP 份（同时匹配旧 .db 与新 .db.gz，按时间统一轮转）
    ls -t "${BACKUP_DIR}"/cs2_inventory_*.db "${BACKUP_DIR}"/cs2_inventory_*.db.gz 2>/dev/null \
        | tail -n +$((KEEP+1)) | xargs -r rm -f
    REMAINING=$(ls "${BACKUP_DIR}"/cs2_inventory_*.db* 2>/dev/null | wc -l)
    echo "[$(date)] 当前保留备份数: ${REMAINING}"
else
    echo "[$(date)] 备份失败！" >&2
    exit 1
fi
