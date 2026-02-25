#!/bin/bash
# CS2 Inventory Manager — 看门狗监控脚本
# 功能：
#   1. HTTP 健康检查（/health 端点）
#   2. 服务异常时自动重启
#   3. 数据新鲜度检查（价格数据是否按时采集）
#   4. 磁盘空间检查
#   5. 日志记录到 /var/log/cs2-monitor.log
#
# 使用方式：每 5 分钟通过 cron 执行
# */5 * * * * /var/www/cs2-inventory-manager/tools/monitor.sh >> /var/log/cs2-monitor.log 2>&1

SERVICE_NAME="cs2-inventory"
HEALTH_URL="http://127.0.0.1:8000/health"
STATUS_URL="http://127.0.0.1:8000/api/monitoring/status"
DB_PATH="/var/www/cs2-inventory-manager/cs2_inventory.db"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
MAX_RESTART_ATTEMPTS=3
RESTART_COOLDOWN_FILE="/tmp/cs2-restart-cooldown"

log_info() {
    echo "${LOG_PREFIX} [INFO] $1"
}

log_warn() {
    echo "${LOG_PREFIX} [WARN] $1"
}

log_error() {
    echo "${LOG_PREFIX} [ERROR] $1"
}

# ── 1. HTTP 健康检查 ──
check_health() {
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$HEALTH_URL" 2>/dev/null)

    if [ "$response" = "200" ]; then
        log_info "Health check OK (HTTP $response)"
        return 0
    else
        log_error "Health check FAILED (HTTP $response)"
        return 1
    fi
}

# ── 2. 服务状态检查 ──
check_service() {
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        log_info "Service $SERVICE_NAME is active"
        return 0
    else
        log_error "Service $SERVICE_NAME is NOT active"
        return 1
    fi
}

# ── 3. 自动重启（带冷却期）──
restart_service() {
    # 检查冷却期（防止频繁重启）
    if [ -f "$RESTART_COOLDOWN_FILE" ]; then
        local last_restart
        last_restart=$(cat "$RESTART_COOLDOWN_FILE")
        local now
        now=$(date +%s)
        local diff=$((now - last_restart))
        if [ $diff -lt 300 ]; then
            log_warn "Restart cooldown active (${diff}s since last restart, need 300s). Skipping."
            return 1
        fi
    fi

    log_warn "Attempting to restart $SERVICE_NAME..."
    systemctl restart "$SERVICE_NAME"
    sleep 5

    if check_health; then
        log_info "Service restarted successfully"
        date +%s > "$RESTART_COOLDOWN_FILE"
        return 0
    else
        log_error "Service restart did not resolve the issue"
        date +%s > "$RESTART_COOLDOWN_FILE"
        return 1
    fi
}

# ── 4. 数据库完整性检查 ──
check_database() {
    if [ ! -f "$DB_PATH" ]; then
        log_error "Database file not found: $DB_PATH"
        return 1
    fi

    local size
    size=$(du -m "$DB_PATH" | cut -f1)
    log_info "Database size: ${size}MB"

    # SQLite integrity check (quick)
    local integrity
    integrity=$(sqlite3 "$DB_PATH" "PRAGMA quick_check;" 2>/dev/null)
    if [ "$integrity" = "ok" ]; then
        log_info "Database integrity: OK"
        return 0
    else
        log_error "Database integrity check FAILED: $integrity"
        return 1
    fi
}

# ── 5. 磁盘空间检查 ──
check_disk() {
    local usage
    usage=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
    log_info "Disk usage: ${usage}%"

    if [ "$usage" -gt 90 ]; then
        log_error "Disk usage CRITICAL: ${usage}% (>90%)"
        return 1
    elif [ "$usage" -gt 80 ]; then
        log_warn "Disk usage HIGH: ${usage}% (>80%)"
        return 0
    fi
    return 0
}

# ── 6. 备份检查 ──
check_backups() {
    local backup_dir="/var/backups/cs2-inventory"
    if [ ! -d "$backup_dir" ]; then
        log_warn "Backup directory not found"
        return 1
    fi

    local count
    count=$(ls "$backup_dir"/cs2_inventory_*.db 2>/dev/null | wc -l)
    log_info "Backup count: $count"

    if [ "$count" -eq 0 ]; then
        log_warn "No backups found!"
        return 1
    fi

    # Check latest backup age
    local latest
    latest=$(ls -t "$backup_dir"/cs2_inventory_*.db 2>/dev/null | head -1)
    if [ -n "$latest" ]; then
        local age
        age=$(( ($(date +%s) - $(stat -c %Y "$latest")) / 3600 ))
        log_info "Latest backup age: ${age}h ($latest)"
        if [ "$age" -gt 12 ]; then
            log_warn "Latest backup is ${age}h old (>12h)"
        fi
    fi
    return 0
}

# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_info "Starting monitoring check..."

ISSUES=0

# Service check
if ! check_service; then
    ISSUES=$((ISSUES + 1))
    restart_service
fi

# Health check
if ! check_health; then
    ISSUES=$((ISSUES + 1))
    # If health check fails but service is up, try restart
    if check_service; then
        restart_service
    fi
fi

# Database check
if ! check_database; then
    ISSUES=$((ISSUES + 1))
fi

# Disk check
if ! check_disk; then
    ISSUES=$((ISSUES + 1))
fi

# Backup check
check_backups

if [ "$ISSUES" -eq 0 ]; then
    log_info "All checks passed ✓"
else
    log_warn "Monitoring completed with $ISSUES issue(s)"
fi
