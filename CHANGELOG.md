# Changelog / 更新日志

## [0.3.0] - 2026-02-25

### 新增 / Added
- 组合价值快照系统：每30分钟自动记录持仓总值、成本、盈亏等数据 / Portfolio snapshot system: auto-records portfolio value, cost, PnL every 30 minutes
- 资产概览页新增组合价值走势图，支持 24h/7d/30d/90d/全部 时间范围 / Portfolio value trend chart on Overview tab with configurable time ranges
- 系统监控卡片：运行状态、运行时间、数据库大小、采集器状态 / System monitor card: status, uptime, DB size, collector state
- 监控 API：`/api/monitoring/status`、`/portfolio-history`、`/data-freshness` / Monitoring API endpoints for health, portfolio history, and data freshness
- 看门狗脚本 `monitor.sh`：每5分钟健康检查，异常自动重启，数据库完整性检查，磁盘空间监控 / Watchdog script with health checks, auto-restart, DB integrity, disk monitoring
- 自动备份脚本 `backup.sh`：每6小时 SQLite 热备份，保留30份 / Auto-backup script: SQLite hot backup every 6h, 30-file retention

## [0.2.0] - 2026-02-24

### 新增 / Added
- 量化分析系统：RSI、布林带、动量、波动率等技术指标 / Quantitative analysis: RSI, Bollinger Bands, momentum, volatility indicators
- 量化分析前端 Tab：Chart.js 价格走势图、信号排名、预警系统 / Analysis frontend tab with Chart.js price charts, signal rankings, alert system
- 套利雷达：跨平台价差检测 / Arbitrage radar: cross-platform spread detection
- APScheduler 定时采集（每30分钟）、日线聚合、信号计算 / Scheduled collection (30min), daily OHLC aggregation, signal computation
- 涨跌色模式切换（A股红涨绿跌 / 美股绿涨红跌） / Color mode toggle (CN red-up / US green-up)
- 浅色/深色主题切换 / Light/dark theme toggle
- 中英文全局语言切换 / Global CN/EN language toggle
- PnL% 排序、CS2 Logo、分类筛选、磨损等级筛选 / PnL% sort, CS2 logo, category & wear filters

## [0.1.0] - 2026-02-22

### 新增 / Added
- 基础库存管理：Steam 库存同步、储物柜追踪 / Core inventory: Steam sync, storage unit tracking
- 悠悠有品集成：租赁导入、库存导入、买入记录匹配 / Youpin integration: lease import, stock import, buy-price matching
- 实时市价刷新（SteamDT + 悠悠有品双源） / Real-time price refresh (SteamDT + Youpin dual source)
- 上架管理：出售/出租货架、改价、批量智能改价 / Listing management: sell/lease shelf, reprice, batch smart reprice
- Web Dashboard：持仓列表、资产概览、盈亏计算 / Web dashboard: inventory list, overview, P&L calculation
- 悠悠有品 SMS 登录、Token 持久化 / Youpin SMS login, token persistence
