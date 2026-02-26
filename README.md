# CS2 Inventory Manager

> **中文** | [English](#english)

CS2 饰品量化交易监控系统 — 集库存管理、实时市价追踪、盈亏分析、量化信号与自动化运维于一体。

---

## 功能概览

**库存管理**
- Steam 库存自动同步（支持 7 天交易保护期物品）
- 储物柜追踪：通过 instance_id 变化自动检测存取事件
- 悠悠有品集成：租赁导入、库存导入、买入记录精确匹配（RSA+AES 加密通信）
- 物品状态机：`in_steam` → `rented_out` → `sold`

**实时定价**
- 双数据源：SteamDT Open API + 悠悠有品官方市价
- 每 30 分钟自动采集全量市价
- 跨平台最低价聚合、手动定价覆盖

**盈亏分析**
- 逐件盈亏计算（成本 vs 市价）
- 组合价值快照：每 30 分钟自动记录持仓总值、成本、PnL
- 组合价值走势图（支持 24h / 7d / 30d / 90d 时间范围）

**量化信号**
- 「CS2 大商决策模型」卖出评分：收益达标度(30%)、年化收益衰减(20%)、持仓集中度(20%)、异常波动(25%)、市场冲击(5%)
- 买入机会评分：超卖、布林下轨、短期回调、跨平台价差、深亏增持
- 技术指标：RSI(14)、布林带、动量、波动率、年化收益率、持仓占比、市场份额、波动 Z 值
- 预警系统、套利雷达（跨平台价差检测）
- 日线 OHLC 聚合 + 历史数据回填

**上架管理**
- 悠悠有品货架：出售 / 出租 / 转租
- 批量智能改价（自动跟价策略）
- 一键上架 / 下架 / 改价

**监控与运维**
- 看门狗脚本：每 5 分钟健康检查，异常自动重启
- SQLite 热备份：每 6 小时备份，保留 30 份
- 数据库完整性检查、磁盘空间监控

**前端**
- 单页应用（Alpine.js + Tailwind CSS + Chart.js）
- 深色 / 浅色主题、中英文切换、涨跌色模式切换
- 网站内置双语更新日志

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · Uvicorn |
| 数据库 | SQLite（aiosqlite）· SQLAlchemy 2.0 |
| 定时任务 | APScheduler（AsyncIO） |
| 前端 | Alpine.js · Tailwind CSS · Chart.js |
| 加密 | PyCryptodome（RSA + AES） |
| 部署 | systemd · Cron · Nginx |

## 项目结构

```
cs2-inventory-manager/
├── main.py                        # FastAPI 入口 + 定时任务
├── requirements.txt
├── .env.example                   # 环境变量模板
├── CHANGELOG.md                   # 更新日志
├── static/index.html              # SPA 前端
├── tools/
│   ├── backup.sh                  # 热备份脚本
│   └── monitor.sh                 # 看门狗脚本
└── app/
    ├── core/                      # 配置 + 数据库引擎
    ├── models/db_models.py        # 8 张表 ORM 模型
    ├── schemas/                   # API 响应模型
    ├── services/                  # 业务逻辑（采集/同步/量化/加密）
    └── api/routes/                # 7 个路由模块
```

## 快速开始

```bash
git clone git@github.com:allureking/cs2-inventory-manager.git
cd cs2-inventory-manager
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # 编辑填入 API Key 和凭证
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

需要的凭证：
- **SteamDT API Key** — [SteamDT 开放平台](https://doc.steamdt.com)
- **Steam Web API Key** — [Steam API Key](https://steamcommunity.com/dev/apikey)
- **Steam 登录 Cookie** — 浏览器 F12 获取 `steamLoginSecure` + `sessionid`
- **悠悠有品 Token** — 在系统 Web 界面中通过短信登录获取

## 定时任务

| 任务 | 频率 | 说明 |
|------|------|------|
| `collect_prices` | 每 30 分钟 | 采集全量市价 |
| `snapshot_portfolio` | 每 30 分钟 | 记录组合价值快照 |
| `aggregate_daily` | 每日 00:05 UTC | 日线 OHLC 聚合 |
| `compute_signals` | 每日 00:10 UTC | 量化信号计算 |
| `cleanup_snapshots` | 每日 01:00 UTC | 清理过期快照 |
| `backup.sh` | 每 6 小时 | SQLite 热备份 |
| `monitor.sh` | 每 5 分钟 | 健康检查 + 自动重启 |

## API 接口

| 模块 | 路径 | 说明 |
|------|------|------|
| 仪表盘 | `/api/dashboard` | 资产概览、持仓列表、市价刷新 |
| 量化分析 | `/api/analysis` | 信号、预警、套利、图表数据 |
| 系统监控 | `/api/monitoring` | 运行状态、组合历史、数据新鲜度 |
| 库存管理 | `/api/inventory` | Steam 同步、成本管理 |
| 悠悠有品 | `/api/youpin` | 导入、市价查询、登录 |
| 上架管理 | `/api/listing` | 上架、下架、改价 |
| 价格查询 | `/api/prices` | SteamDT 价格接口 |

---

<a id="english"></a>

> [中文](#cs2-inventory-manager) | **English**

# CS2 Inventory Manager

A quantitative trading & monitoring system for CS2 skins — inventory management, real-time pricing, P&L analysis, quant signals, and automated operations in one place.

---

## Features

**Inventory Management**
- Auto-sync Steam inventory (including 7-day trade-hold items)
- Storage unit tracking via instance_id change detection
- Youpin898 integration: lease import, stock import, precision buy-price matching (RSA+AES encrypted)
- Item state machine: `in_steam` → `rented_out` → `sold`

**Real-time Pricing**
- Dual data source: SteamDT Open API + Youpin official market prices
- Auto-collect prices every 30 minutes
- Cross-platform lowest price aggregation, manual price override

**P&L Analysis**
- Per-item P&L calculation (cost vs. market price)
- Portfolio snapshots: auto-record total value, cost, PnL every 30 minutes
- Portfolio value trend chart (24h / 7d / 30d / 90d time ranges)

**Quantitative Signals**
- "CS2 Dealer Decision Model" sell score: Target P&L (30%), Annual Return Decay (20%), Concentration (20%), Volatility Anomaly (25%), Market Impact (5%)
- Buy opportunity score: oversold, lower BB, dip, cross-platform spread, loss averaging
- Technical indicators: RSI(14), Bollinger Bands, momentum, volatility, annualized return, concentration %, market share %, volatility z-score
- Alert system, arbitrage radar (cross-platform spread detection)
- Daily OHLC aggregation + historical data backfill

**Listing Management**
- Youpin shelf management: sell / lease / sublet
- Batch smart repricing (auto-undercut strategy)
- One-click list / delist / reprice

**Monitoring & Ops**
- Watchdog script: health checks every 5 min, auto-restart on failure
- SQLite hot backup: every 6 hours, 30-file retention
- DB integrity checks, disk space monitoring

**Frontend**
- Single-page app (Alpine.js + Tailwind CSS + Chart.js)
- Dark / light theme, CN / EN language toggle, color mode toggle
- Built-in bilingual changelog

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite (aiosqlite) · SQLAlchemy 2.0 |
| Scheduler | APScheduler (AsyncIO) |
| Frontend | Alpine.js · Tailwind CSS · Chart.js |
| Encryption | PyCryptodome (RSA + AES) |
| Deployment | systemd · Cron · Nginx |

## Quick Start

```bash
git clone git@github.com:allureking/cs2-inventory-manager.git
cd cs2-inventory-manager
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # Fill in your API keys and credentials
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Required credentials:
- **SteamDT API Key** — [SteamDT Open Platform](https://doc.steamdt.com)
- **Steam Web API Key** — [Steam API Key](https://steamcommunity.com/dev/apikey)
- **Steam Login Cookie** — Get `steamLoginSecure` + `sessionid` from browser DevTools
- **Youpin Token** — Obtain via SMS login in the web UI

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `collect_prices` | Every 30 min | Collect market prices |
| `snapshot_portfolio` | Every 30 min | Record portfolio snapshot |
| `aggregate_daily` | 00:05 UTC daily | Daily OHLC aggregation |
| `compute_signals` | 00:10 UTC daily | Compute quant signals |
| `cleanup_snapshots` | 01:00 UTC daily | Purge expired snapshots |
| `backup.sh` | Every 6h | SQLite hot backup |
| `monitor.sh` | Every 5 min | Health check + auto-restart |

## API Endpoints

| Module | Path | Description |
|--------|------|-------------|
| Dashboard | `/api/dashboard` | Overview, holdings, price refresh |
| Analysis | `/api/analysis` | Signals, alerts, arbitrage, charts |
| Monitoring | `/api/monitoring` | Status, portfolio history, data freshness |
| Inventory | `/api/inventory` | Steam sync, cost management |
| Youpin | `/api/youpin` | Import, market prices, login |
| Listing | `/api/listing` | List, delist, reprice |
| Prices | `/api/prices` | SteamDT price queries |
