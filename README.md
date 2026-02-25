# CS2 Inventory Manager

CS2 饰品量化交易监控系统 — 集库存管理、实时市价追踪、盈亏分析、量化信号与自动化运维于一体。

A quantitative trading & monitoring system for CS2 skins — inventory management, real-time pricing, P&L analysis, quant signals, and automated operations in one place.

## Features / 功能概览

### 库存管理 / Inventory Management
- Steam 库存自动同步（支持 7 天保护期物品）
- 储物柜追踪：自动检测存取事件
- 悠悠有品集成：租赁导入、库存导入、买入记录精确匹配（RSA+AES 加密）
- 状态机追踪：`in_steam` → `rented_out` → `sold`

### 实时定价 / Real-time Pricing
- 双数据源：SteamDT Open API + 悠悠有品官方市价
- 每 30 分钟自动采集全量市价（APScheduler）
- 跨平台最低价聚合
- 手动定价支持

### 盈亏分析 / P&L Analysis
- 逐件盈亏计算（成本 vs 市价）
- 组合价值快照：每 30 分钟记录持仓总值、成本、PnL
- 组合价值走势图（Chart.js，支持 24h/7d/30d/90d 时间范围）

### 量化信号 / Quantitative Signals
- 技术指标：RSI(14)、布林带(%B / Width)、7/30 天动量、年化波动率
- 综合评分：卖出评分 + 机会评分（0-100）
- 预警系统：自动生成交易提醒
- 套利雷达：跨平台价差检测与排名
- 日线 OHLC 聚合 + 历史回填

### 上架管理 / Listing Management
- 悠悠有品货架管理：出售 / 出租 / 转租
- 批量智能改价（自动跟价策略）
- 一键上架 / 下架 / 改价

### 监控与运维 / Monitoring & Ops
- 看门狗脚本：每 5 分钟健康检查，异常自动重启
- SQLite 热备份：每 6 小时自动备份，保留 30 份
- 数据库完整性检查、磁盘空间监控
- 系统状态 API：运行时间、数据新鲜度、采集器状态

### 前端 / Frontend
- 单页应用（Alpine.js + Tailwind CSS + Chart.js）
- 深色 / 浅色主题切换
- 中文 / English 全局语言切换
- 涨跌色模式（A 股红涨绿跌 / 美股绿涨红跌）
- 网站内置更新日志（双语）

## Tech Stack / 技术栈

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite (aiosqlite) · SQLAlchemy 2.0 |
| Scheduler | APScheduler (AsyncIO) |
| Frontend | Alpine.js · Tailwind CSS · Chart.js |
| Encryption | PyCryptodome (RSA + AES for Youpin API) |
| Deployment | systemd · Cron · Nginx (reverse proxy) |

## Project Structure / 项目结构

```
cs2-inventory-manager/
├── main.py                        # FastAPI app + APScheduler
├── requirements.txt
├── .env.example                   # 环境变量模板
├── CHANGELOG.md                   # 更新日志
├── static/
│   └── index.html                 # SPA 前端
├── tools/
│   ├── backup.sh                  # SQLite 热备份脚本
│   └── monitor.sh                 # 看门狗监控脚本
└── app/
    ├── core/
    │   ├── config.py              # Pydantic Settings
    │   └── database.py            # SQLAlchemy async engine
    ├── models/
    │   └── db_models.py           # 8 ORM models
    ├── schemas/
    │   ├── steamdt.py             # SteamDT response schemas
    │   └── steam.py               # Steam API schemas
    ├── services/
    │   ├── steamdt.py             # SteamDT API client
    │   ├── steam.py               # Steam inventory sync
    │   ├── youpin.py              # Youpin API (RSA/AES)
    │   ├── youpin_listing.py      # Listing management
    │   ├── quant_engine.py        # Technical indicators
    │   └── collector.py           # Background jobs
    └── api/routes/
        ├── prices.py              # Price query
        ├── items.py               # Item catalog
        ├── inventory.py           # Portfolio sync & cost
        ├── youpin.py              # Youpin import/sync
        ├── listing.py             # Listing management
        ├── dashboard.py           # Dashboard aggregation
        ├── analysis.py            # Quant analysis
        └── monitoring.py          # System monitoring
```

## Quick Start / 快速开始

### 1. Clone & Install

```bash
git clone git@github.com:allureking/cs2-inventory-manager.git
cd cs2-inventory-manager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys and credentials
```

Required credentials:
- **SteamDT API Key** — [申请地址](https://doc.steamdt.com)
- **Steam Web API Key** — [Steam API Key](https://steamcommunity.com/dev/apikey)
- **Steam Login Cookie** — `steamLoginSecure` + `sessionid` from browser
- **Youpin Token** — via SMS login in the web UI

### 3. Run

```bash
# Development
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Production (systemd)
sudo cp cs2-inventory.service /etc/systemd/system/
sudo systemctl enable --now cs2-inventory
```

### 4. Setup Monitoring

```bash
# Add cron jobs
chmod +x tools/monitor.sh tools/backup.sh
crontab -e
# Add:
# */5 * * * * /path/to/tools/monitor.sh >> /var/log/cs2-monitor.log 2>&1
# 0 */6 * * * /path/to/tools/backup.sh >> /var/log/cs2-backup.log 2>&1
```

## Scheduled Tasks / 定时任务

| Task | Schedule | Description |
|------|----------|-------------|
| `collect_prices` | Every 30 min | 采集全量市价 / Collect market prices |
| `snapshot_portfolio` | Every 30 min | 记录组合快照 / Record portfolio snapshot |
| `aggregate_daily` | 00:05 UTC | 日线 OHLC 聚合 / Daily OHLC aggregation |
| `compute_signals` | 00:10 UTC | 量化信号计算 / Compute quant signals |
| `cleanup_snapshots` | 01:00 UTC | 清理旧快照 / Purge old snapshots |
| `backup.sh` | Every 6h | SQLite 热备份 / Hot backup |
| `monitor.sh` | Every 5 min | 健康检查 + 自动重启 / Health check + auto-restart |

## API Endpoints

| Module | Prefix | Description |
|--------|--------|-------------|
| Dashboard | `/api/dashboard` | 资产概览、持仓列表、市价刷新 |
| Analysis | `/api/analysis` | 量化信号、预警、套利、图表 |
| Monitoring | `/api/monitoring` | 系统状态、组合历史、数据新鲜度 |
| Inventory | `/api/inventory` | Steam 同步、成本管理 |
| Youpin | `/api/youpin` | 悠悠有品导入、市价、登录 |
| Listing | `/api/listing` | 上架、下架、改价 |
| Prices | `/api/prices` | SteamDT 价格查询 |

## License

MIT
