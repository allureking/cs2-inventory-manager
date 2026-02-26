# Changelog / 更新日志

## [0.5.0] - 2026-02-26

### 新增 / Added
- **CSQAQ 数据 API 集成**：自动映射 202 个饰品的 CSQAQ good_id，每日拉取市场租金、Steam 成交量、全球存世量 / **CSQAQ Data API integration**: auto-maps 202 items via Chinese name search, daily sync of market rental, Steam turnover, global supply
- 信号面板新增「日租金」「Steam 成交量」「全球存世量」三组数据卡片 / Signal detail panel adds 3 new data cards: daily rent, Steam turnover, global supply
- 租金年化率现在使用 CSQAQ 市场数据（全部 202 个饰品可显示），不再依赖用户自有货架 / Rental yield now uses CSQAQ market data (all 202 items), no longer depends on user's own shelf
- 排名表支持按 `rental_annual`、`steam_turnover`、`global_supply` 排序 / Rankings support sorting by rental yield, turnover, supply
- 新增 `POST /api/analysis/csqaq-sync` 手动触发同步 + `GET /api/analysis/csqaq-status` 状态轮询端点 / New CSQAQ sync trigger and status polling API endpoints
- 前端新增「CSQAQ 同步」按钮，支持后台轮询进度 / Frontend adds "CSQAQ Sync" button with background progress polling
- 定时任务：每日 00:02 UTC 自动执行 CSQAQ 数据同步 / Scheduled job: daily CSQAQ sync at 00:02 UTC

### 变更 / Changed
- 卖出评分新增「租金年化修正」：年化租金 >15% 降低卖出分（高租金饰品值得继续持有出租） / Sell score adds rental correction: rental yield >15% reduces sell signal (high-rent items worth holding)
- 买入机会评分新增「租金收益」维度(10%)：高租金增加增持价值 / Opportunity score adds rental yield dimension (10%): high rent boosts buy signal
- icon_url 覆盖率从 63.8% 提升至 94.5%，item_type 覆盖率从 0.8% 提升至 88.4% / icon_url coverage from 63.8% to 94.5%, item_type from 0.8% to 88.4%
- SQLite 启用 WAL 模式 + 30s 超时，解决后台同步与前端请求并发锁定问题 / SQLite WAL mode + 30s timeout to fix concurrent lock issues during background sync

## [0.4.0] - 2026-02-26

### 新增 / Added
- **卖出评分重构为「CS2 大商决策模型」**：五维度加权 — 收益达标度(30%)、年化收益衰减(20%)、持仓集中度(20%)、异常波动(25%)、市场冲击(5%) / **Sell score rewritten as "CS2 Dealer Decision Model"**: 5-dimension weighted scoring — Target P&L(30%), Annual Return Decay(20%), Concentration(20%), Volatility Anomaly(25%), Market Impact(5%)
- 买入机会评分新增「深亏增持」维度(20%)：远低于目标收益时触发增持信号 / Buy opportunity score adds "loss averaging" dimension (20%): triggers buy signal when deep in loss
- 新增 5 个量化指标仪表盘：年化收益率、持有件数、持仓占比、市场份额、波动 Z 值 / 5 new signal gauges: annualized return, holding count, concentration %, market share %, volatility z-score
- 持仓信息卡新增「持有件数」和「目标收益率」显示 / Ownership card now shows holding count and target P&L
- 数据库新增 `target_pnl_pct`（单品目标收益率）和 5 个量化信号维度字段 / DB adds `target_pnl_pct` (per-item target return) and 5 signal dimension columns
- 组合快照新增按状态拆分市值（Steam 库存 / 出租中） / Portfolio snapshots now split market value by status (in_steam / rented_out)

### 变更 / Changed
- 卖出评分基线从 50 调整为 45（无信号 = 不急卖） / Sell score baseline adjusted from 50 to 45 (no signal = don't rush to sell)
- 原 RSI/布林带/动量/ATH 指标降级为「异常波动」维度的子因子 / Original RSI/BB/Momentum/ATH demoted to sub-factors under "Volatility Anomaly" dimension
- 年化收益衰减维度仅在盈利状态下生效，避免亏损时误判 / Annual return decay only activates when profitable, avoiding false signals during losses
- 排名表和信号 API 新增年化收益、持仓集中度等排序维度 / Rankings and signals API support sorting by new dimensions

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
