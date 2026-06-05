    const _CHANGELOG = Object.freeze([
          {
            version: '0.6.0', date: '2026-03-21', major: true,
            title_cn: '每日收益追踪系统 — 替代 Excel 手动记录',
            title_en: 'Daily Income Tracker — Replace Manual Excel Tracking',
            added: [
              ['每日收益追踪系统：自动抓取出租件数、总价值、日租金、年化收益率、库存价值、涨跌', 'Daily income tracker: auto-capture rental count, value, income, annualized returns, inventory value'],
              ['每日 00:01 UTC 自动快照（悠悠 API + DB 查询，几秒完成）', 'Auto snapshot daily at 00:01 UTC (Youpin API + DB, seconds)'],
              ['月度汇总：总收入、服务费(20%)、净租金、净租金年化', 'Monthly summary: income, service fee (20%), net rental, annualized'],
              ['Excel 导入/导出（xlsx 格式）', 'Excel import/export (xlsx format)'],
              ['前端「收益追踪」Tab：汇总卡片 + 趋势图表 + 月度表 + 每日明细', 'Frontend "Income Tracker" tab: cards + charts + monthly + daily table'],
              ['历史数据导入 123 条记录（2025-10 至 2026-03）', 'Historical data: 123 records imported (Oct 2025 - Mar 2026)'],
            ],
            commits: [
              { hash: '728e065', msg: 'feat: 每日收益追踪系统 — 替代 Excel 手动记录', date: '03-21' },
            ],
          },
          {
            version: '0.5.2', date: '2026-03-21', major: false,
            title_cn: '全面代码审查 — 16 项 Bug 修复与架构加固',
            title_en: 'Comprehensive Code Audit — 16 Bug Fixes & Architecture Hardening',
            fixed: [
              ['购买记录匹配失败：assertId 拼写错误修复', 'Buy record matching broken: fixed assertId typo (should be assetId)'],
              ['物品"消失"bug：unknown 状态加入合法集合，新增「待确认」过滤', 'Items disappearing: unknown status added to VALID_STATUSES with filter option'],
              ['市价刷新状态卡死：添加 finally 防护', 'Market refresh state stuck: added finally guard'],
              ['前端 22 个空 catch 块补充错误提示', '22 empty catch blocks now show proper error messages'],
              ['轮询计时器竞态条件：防止重复 setInterval', 'Polling timer race condition: prevent duplicate intervals'],
              ['浮点定价精度：calc_sell_price 改用 Decimal', 'Float pricing precision: calc_sell_price uses Decimal'],
              ['磨损值匹配容差从 1e-8 放宽到 0.0001', 'Wear value matching tolerance relaxed from 1e-8 to 0.0001'],
              ['表单输入验证：saveReprice / smartListItem', 'Form validation added to saveReprice / smartListItem'],
            ],
            changed: [
              ['CORS 收紧为实际部署域名', 'CORS restricted to actual deployment domains'],
              ['Token 持久化原子写入 + chmod 600', 'Token persistence: atomic writes + chmod 600'],
              ['市价刷新和价格采集添加 asyncio.Lock 并发保护', 'asyncio.Lock for market refresh and price collection'],
              ['调度任务错开执行（:00/:30 vs :15/:45）+ max_instances=1', 'Staggered scheduler (:00/:30 vs :15/:45) + max_instances=1'],
              ['数据库迁移成功时记录日志', 'Migration logging for successful column additions'],
              ['图片加载失败统一使用 placeholder SVG', 'Unified image error handling with placeholder SVG'],
            ],
            added: [
              ['19 个定价算法单元测试（outlier/止盈率/浮点精度/租赁）', '19 pricing algorithm unit tests (outlier/take-profit/float precision/lease)'],
            ],
            commits: [
              { hash: '9f66378', msg: 'fix: 全面代码审查修复16项bug与改进', date: '03-21' },
            ],
          },
          {
            version: '0.5.1', date: '2026-02-26', major: false,
            title_cn: 'Bug 修复 — ATH 数据源 / 年化收益拆分 / 大会员开关 / 图表修复',
            title_en: 'Bug Fixes — ATH Data Source / Return Split / VIP Toggle / Chart Fix',
            fixed: [
              ['ATH 数据不准确：新增 CSQAQ API 长期历史数据支持，本地 45 天数据仅作兜底', 'Inaccurate ATH: Added CSQAQ API long-term historical data, local 45-day data as fallback'],
              ['资产概览市值导入后不刷新：同步完成后自动刷新', 'Market value not refreshing after import: auto-refresh on completion'],
              ['组合走势图曲线显隐按钮无效：改用 Chart.js 标准 API', 'Chart toggle buttons broken: use Chart.js standard setDatasetVisibility API'],
            ],
            changed: [
              ['年化收益拆分为「盈亏率」+ 「含租预期收益率」，更直观', 'Annual return split into P&L Rate + Projected Return with rental income'],
              ['新增悠悠大会员开关：310 天 vs 188 天有效出租', 'Added Youpin VIP toggle: 310d vs 188d effective rental days'],
              ['数据库新增 pnl_rate、projected_annual_return、csqaq_ath_price 字段', 'DB adds pnl_rate, projected_annual_return, csqaq_ath_price columns'],
            ],
            commits: [
              { hash: 'bcfe55f', msg: 'fix: ATH数据源优化 + 年化收益拆分 + 大会员开关 + 图表修复', date: '02-26' },
            ],
          },
          {
            version: '0.5.0', date: '2026-02-26', major: true,
            title_cn: 'CSQAQ 数据集成 — 租金/成交量/存世量全覆盖',
            title_en: 'CSQAQ Data Integration — Full Rental, Turnover & Supply Coverage',
            added: [
              ['CSQAQ API 集成：自动映射 202 个饰品，每日拉取市场租金、Steam 成交量、全球存世量', 'CSQAQ API integration: auto-maps 202 items, daily sync of market rental, Steam turnover, global supply'],
              ['信号面板新增「日租金」「Steam 成交量」「全球存世量」数据卡片', 'Signal panel adds daily rent, Steam turnover, global supply data cards'],
              ['租金年化率使用 CSQAQ 市场数据，202 个饰品全部可显示', 'Rental yield now uses CSQAQ market data, all 202 items covered'],
              ['排名表支持按租金年化、成交量、存世量排序', 'Rankings support sorting by rental yield, turnover, supply'],
              ['CSQAQ 同步按钮 + 后台进度轮询', 'CSQAQ Sync button with background progress polling'],
              ['定时任务：每日 00:02 UTC 自动 CSQAQ 数据同步', 'Scheduled daily CSQAQ sync at 00:02 UTC'],
            ],
            changed: [
              ['卖出评分新增租金年化修正：高租金饰品降低卖出信号', 'Sell score adds rental correction: high-rent items get lower sell signal'],
              ['买入机会评分新增租金收益维度(10%)', 'Opportunity score adds rental yield dimension (10%)'],
              ['icon_url 覆盖率 63.8%→94.5%，item_type 覆盖率 0.8%→88.4%', 'icon_url coverage 63.8%→94.5%, item_type 0.8%→88.4%'],
              ['SQLite 启用 WAL 模式，解决后台同步并发锁定问题', 'SQLite WAL mode fixes concurrent lock issues during background sync'],
            ],
            commits: [
              { hash: 'c22fc18', msg: 'feat: CSQAQ data integration — rental, turnover & supply coverage', date: '02-26' },
            ],
          },
          {
            version: '0.4.0', date: '2026-02-26', major: true,
            title_cn: 'CS2 大商决策模型 — 卖出评分全面重构',
            title_en: 'CS2 Dealer Decision Model — Sell Score Overhaul',
            added: [
              ['卖出评分重构为五维度「大商决策模型」：收益达标度(30%)、年化收益衰减(20%)、持仓集中度(20%)、异常波动(25%)、市场冲击(5%)', 'Sell score rewritten as 5-dimension "Dealer Decision Model": Target P&L(30%), Annual Return Decay(20%), Concentration(20%), Volatility Anomaly(25%), Market Impact(5%)'],
              ['买入机会评分新增「深亏增持」维度(20%)，远低于目标收益时触发增持信号', 'Buy opportunity score adds "loss averaging" dimension (20%): triggers buy signal when deep in loss'],
              ['5 个新量化指标仪表盘：年化收益率、持有件数、持仓占比、市场份额、波动 Z 值', '5 new signal gauges: annualized return, holding count, concentration %, market share %, volatility z-score'],
              ['持仓信息卡新增「持有件数」和「目标收益率」', 'Ownership card now shows holding count and target P&L'],
              ['数据库新增 target_pnl_pct 及 5 个信号维度字段', 'DB adds target_pnl_pct and 5 signal dimension columns'],
              ['组合快照按状态拆分市值（Steam 库存 / 出租中）', 'Portfolio snapshots split market value by status (in_steam / rented_out)'],
            ],
            changed: [
              ['卖出评分基线从 50 调整为 45（无信号 = 不急卖）', 'Sell score baseline adjusted from 50 to 45 (no signal = don\'t rush to sell)'],
              ['原 RSI/布林带/动量/ATH 降级为「异常波动」子因子', 'RSI/BB/Momentum/ATH demoted to sub-factors under Volatility Anomaly dimension'],
              ['年化收益衰减仅在盈利时生效，避免亏损误判', 'Annual return decay only activates when profitable'],
              ['排名表和信号 API 支持按新维度排序', 'Rankings and signals API support sorting by new dimensions'],
            ],
            commits: [
              { hash: 'eb10220', msg: 'feat: CS2 dealer decision model — complete sell score overhaul', date: '02-26' },
            ],
          },
          {
            version: '0.3.0', date: '2026-02-25', major: true,
            title_cn: '24/7 监控、组合快照与趋势可视化',
            title_en: '24/7 Monitoring, Portfolio Snapshots & Trend Visualization',
            added: [
              ['组合价值快照系统：每30分钟自动记录持仓总值、成本、盈亏数据', 'Portfolio snapshot system: auto-records value, cost, P&L every 30 minutes'],
              ['资产概览页「组合价值走势图」，支持 24h/7d/30d/90d/全部 时间范围', 'Portfolio value trend chart on Overview tab with 24h/7d/30d/90d/all ranges'],
              ['系统监控卡片：运行状态、运行时间、数据库大小、采集器状态', 'System monitor card: status, uptime, DB size, collector state'],
              ['监控 API：系统健康检查、组合历史、数据新鲜度', 'Monitoring API: health check, portfolio history, data freshness endpoints'],
              ['看门狗脚本 monitor.sh：每5分钟健康检查，异常自动重启', 'Watchdog script monitor.sh: health checks every 5min, auto-restart on failure'],
              ['自动备份脚本 backup.sh：每6小时 SQLite 热备份，保留30份', 'Auto-backup script backup.sh: SQLite hot backup every 6h, 30-file retention'],
            ],
            commits: [
              { hash: '155a359', msg: 'feat: 24/7 monitoring, portfolio snapshots, and trend visualization', date: '02-25' },
              { hash: '66caa2a', msg: 'docs: add bilingual CHANGELOG with version history', date: '02-25' },
            ],
          },
          {
            version: '0.2.1', date: '2026-02-24', major: false,
            title_cn: '稳定性修复与性能优化',
            title_en: 'Stability Fixes & Performance Optimization',
            fixed: [
              ['全局 i18n 修复、浅色模式样式、租金年化率计算、稀有度颜色、图片显示', 'Global i18n fixes, light mode styles, rental yield calc, rarity colors, images'],
              ['导入/同步改为后台任务，避免 504 超时', 'Convert import/sync to background tasks to avoid 504 timeout'],
              ['Token 持久化到磁盘，进程重启后自动恢复', 'Persist runtime token to disk to survive process restarts'],
            ],
            commits: [
              { hash: 'db7cfc4', msg: 'fix: 6 bugs — global i18n, light mode, rental yield, rarity colors, images, color sync', date: '02-24' },
              { hash: '6f14b35', msg: 'fix: convert import/sync to background tasks to avoid 504 timeout', date: '02-24' },
              { hash: '06ea3fb', msg: 'fix: persist runtime token to disk to survive process restarts', date: '02-24' },
            ],
          },
          {
            version: '0.2.0', date: '2026-02-22', major: true,
            title_cn: '量化分析系统与 UI 大升级',
            title_en: 'Quantitative Analysis System & Major UI Upgrade',
            added: [
              ['量化分析后端：RSI(14)、布林带、7/30天动量、年化波动率等技术指标', 'Quant analysis backend: RSI(14), Bollinger Bands, 7/30d momentum, annualized volatility'],
              ['量化分析前端 Tab：Chart.js 价格走势图、信号排名、预警系统', 'Analysis frontend tab: Chart.js price charts, signal rankings, alert system'],
              ['APScheduler 定时采集（每30分钟）、日线 OHLC 聚合、自动信号计算', 'APScheduler collection (30min), daily OHLC aggregation, auto signal computation'],
              ['套利雷达：跨平台价差检测与排名', 'Arbitrage radar: cross-platform spread detection & ranking'],
              ['浅色/深色主题切换', 'Light/dark theme toggle'],
              ['中英文全局语言切换', 'Global CN/EN language toggle'],
              ['涨跌色模式切换（A股红涨绿跌 / 美股绿涨红跌）', 'Color mode toggle (CN red=up / US green=up)'],
              ['PnL% 排序、CS2 Logo、武器分类筛选、磨损等级筛选', 'PnL% sort, CS2 logo, weapon category & wear grade filters'],
              ['饰品图片显示、稀有度颜色标识', 'Item images display, rarity color coding'],
              ['VIP 等级设置、批量智能改价', 'VIP level setting, batch smart repricing'],
            ],
            fixed: [
              ['8项 UI 修复：命名规范、浅色主题、稀有度颜色、PnL 拆分、tooltip、色彩同步', '8 UI fixes: naming, light theme, rarity colors, PnL split, tooltips, color sync'],
              ['密集回填（45个日数据点）、图表零价填充、排名筛选', 'Dense backfill (45 daily points), chart 0-price fill, rankings filter'],
              ['稀有度颜色修正、分类/磨损筛选扩展、出租列表图片', 'Rarity color fixes, expanded category/wear filters, images in rented list'],
              ['取消转租 orderId、改价 long_lease_unit、短信登录回退、下架刷新', 'Cancel-sublet orderId, reprice long_lease_unit, SMS fallback, delist refresh'],
            ],
            commits: [
              { hash: '82ee8d3', msg: 'feat: quant analysis backend — price_history, signals, alerts, APScheduler collector', date: '02-22' },
              { hash: 'd5a3430', msg: 'feat: 量化分析 frontend tab with Chart.js price charts', date: '02-22' },
              { hash: '78726ed', msg: 'feat: analysis UI — exclude Steam from spreads, item banners, clickable distribution', date: '02-22' },
              { hash: '4a7e012', msg: 'feat: PnL% sort, light/dark theme, CS2 logo, hide VIP, global lang toggle', date: '02-22' },
              { hash: '18ec587', msg: 'feat: VIP level, batch smart reprice, item images, rarity colors, CN/EN toggle', date: '02-21' },
              { hash: '4954891', msg: 'fix: 8 bugs — naming, light theme, rarity colors, PnL split, tooltips, color toggle', date: '02-22' },
              { hash: '3eaf020', msg: 'fix: dense backfill (45 daily points), chart 0-price fill, rankings filter', date: '02-22' },
              { hash: 'ababa30', msg: 'fix: rarity colors, expanded categories/wear filters, images in rented list', date: '02-22' },
              { hash: '6087081', msg: 'fix: cancel-sublet orderId, reprice long_lease_unit, SMS fallback, delist refresh', date: '02-22' },
            ],
          },
          {
            version: '0.1.0', date: '2026-02-21', major: true,
            title_cn: '初始版本 — 库存管理与交易系统',
            title_en: 'Initial Release — Inventory Management & Trading System',
            added: [
              ['Steam 库存同步：通过 Steam Web API 自动同步全量库存', 'Steam inventory sync via Steam Web API with full pagination'],
              ['储物柜追踪：通过 instance_id 变化检测存取事件', 'Storage unit tracking: detect deposit/withdraw via instance_id changes'],
              ['悠悠有品集成：租赁导入、库存导入、买入记录精确匹配', 'Youpin integration: lease import, stock import, precision buy-price matching'],
              ['RSA+AES 加密的悠悠有品市场查询', 'RSA+AES encrypted Youpin market queries'],
              ['实时市价刷新（SteamDT + 悠悠有品双数据源）', 'Real-time price refresh (SteamDT + Youpin dual source)'],
              ['上架管理：出售/出租货架、改价、批量操作', 'Listing management: sell/lease shelf, reprice, batch operations'],
              ['Web Dashboard：持仓列表、资产概览、盈亏计算', 'Web dashboard: inventory list, overview, P&L calculation'],
              ['手动定价支持：为无自动匹配的饰品设置购入价', 'Manual pricing: set purchase price for items without auto-match'],
              ['悠悠有品 SMS 登录与 Token 管理', 'Youpin SMS login & token management'],
              ['分页、搜索、多维度排序', 'Pagination, search, multi-column sorting'],
            ],
            commits: [
              { hash: '453ac86', msg: 'Initial commit', date: '02-21' },
              { hash: '4403628', msg: 'Phase 1', date: '02-21' },
              { hash: '7be5dbb', msg: 'feat: implement Youpin (悠悠有品) API integration (Phase 3.5)', date: '02-21' },
              { hash: '91bf384', msg: 'feat: import Youpin lease positions as primary inventory data source', date: '02-21' },
              { hash: '00877fd', msg: 'feat: add interactive web dashboard with manual price support', date: '02-21' },
              { hash: 'a438768', msg: 'feat: add real-time market price refresh and P&L dashboard (Phase 4)', date: '02-21' },
              { hash: '2fb3452', msg: 'feat: Phase A+B — Youpin market prices, template-id sync, listing management', date: '02-21' },
              { hash: 'be1e2d0', msg: 'feat: fix P&L calc, add sort by market price/pnl, add rented-out & sublet tabs', date: '02-21' },
              { hash: '539f498', msg: 'fix: delist format, split rented/sublet states, add unlisted tab, reprice modal', date: '02-21' },
              { hash: '12666dc', msg: 'fix: Android headers, SMS login, operation payloads, zero-CD shelf, batch ops', date: '02-21' },
            ],
          },
    ]);

    const _I18N = Object.freeze({
          tab_inventory: ['持仓列表', 'Inventory'], tab_overview: ['概览', 'Overview'], tab_listing: ['上架管理', 'Listing'], tab_analysis: ['量化分析', 'Analysis'], tab_tracker: ['收益追踪', 'Income Tracker'], tab_changelog: ['更新日志', 'Changelog'],
          tracker_title: ['每日收益追踪', 'Daily Income Tracker'], tracker_subtitle: ['自动记录出租收益、库存价值与年化收益率', 'Auto-track rental income, inventory value & annualized returns'], tracker_snapshot: ['刷新今日', 'Refresh Today'], tracker_snapshotting: ['刷新中…', 'Refreshing…'], tracker_import: ['导入Excel', 'Import Excel'], tracker_export: ['导出Excel', 'Export Excel'], tracker_monthly_title: ['月度汇总', 'Monthly Summary'],
          tracker_col_date: ['日期', 'Date'], tracker_col_rented: ['出租件数', 'Rented'], tracker_col_value: ['出租价值', 'Value'], tracker_col_income: ['日租金', 'Daily Income'], tracker_col_short: ['短租年化', 'Short Annual'], tracker_col_long: ['长租年化', 'Long Annual'], tracker_col_combined: ['综合年化', 'Combined'], tracker_col_per_item: ['单件/天', 'Per Item/Day'], tracker_col_inv_count: ['总库存', 'Total Inv'], tracker_col_inv_value: ['库存价值', 'Inv Value'], tracker_col_change: ['涨跌', 'Change'], tracker_col_index: ['大盘指数', 'Market Index'],
          btn_unpriced: ['未定价', 'Unpriced'], btn_sync: ['同步库存', 'Sync Inventory'], btn_syncing: ['同步中…', 'Syncing…'], btn_match_records: ['匹配记录', 'Match Records'], btn_refresh_price: ['刷新市价', 'Refresh Prices'], btn_login_youpin: ['登录悠悠', 'Login YouPin'], btn_switch_account: ['切换账号', 'Switch'], syncing_wait: ['同步中，请耐心等待…', 'Syncing, please wait…'], last_sync: ['上次同步', 'Last sync'], market_price: ['市价', 'Price at'], color_cn_tip: ['红涨绿跌（A股），点击切换', 'Red=Up Green=Down (CN), click to switch'], color_us_tip: ['绿涨红跌（美股），点击切换', 'Green=Up Red=Down (US), click to switch'],
          total_cost: ['总持仓成本', 'Total Cost'], active_holdings: ['活跃持仓', 'Active Holdings'], pricing_status: ['定价情况', 'Pricing Status'], quick_actions: ['快捷操作', 'Quick Actions'], cost_rented: ['出租', 'Rented'], cost_steam: ['Steam', 'Steam'], price_coverage: ['定价覆盖', 'Coverage'], auto_priced: ['自动定价', 'Auto'], manual_priced: ['手动定价', 'Manual'], unpriced: ['未定价', 'Unpriced'], goto_unpriced: ['未定价饰品', 'Unpriced Items'], goto_rented: ['出租中', 'Rented Out'], goto_all: ['全部持仓', 'All Holdings'],
          market_value: ['当前市值', 'Market Value'], in_steam_value: ['库存市值', 'In-Steam Value'], rented_out_value: ['出租市值', 'Rented Value'], no_market_price: ['暂无市价', 'No Price Data'], click_refresh: ['点击「刷新市价」获取实时数据', 'Click "Refresh Prices" to get live data'], pnl_amount: ['盈亏金额', 'P&L Amount'], pnl_rate: ['盈亏率', 'P&L Rate'], based_on_estimate: ['基于已有市价估算', 'Based on available market prices'], need_data: ['需要成本价 + 市价数据', 'Need cost + price data'], wait_refresh: ['待市价刷新后计算', 'Pending price refresh'],
          status_distribution: ['持仓状态分布', 'Status Distribution'], portfolio_trend: ['组合价值走势', 'Portfolio Value Trend'], portfolio_no_data: ['暂无数据', 'No data available'], data_points: ['个数据点', 'data points'], chart_cat_value: ['组合价值', 'Portfolio Value'], chart_cat_rental: ['租赁走势', 'Rental Trend'], chart_pnl_pct: ['涨跌比', 'P&L %'], chart_rented_value: ['出租价值', 'Rented Value'],
          system_monitor: ['系统监控', 'System Monitor'], sys_status: ['运行状态', 'Status'], sys_uptime: ['运行时间', 'Uptime'], sys_db_size: ['数据库大小', 'DB Size'], sys_collector: ['采集器', 'Collector'], btn_refresh: ['刷新', 'Refresh'],
          ts_price: ['市价更新', 'Prices'], ts_portfolio: ['组合快照', 'Snapshot'], ts_signal: ['信号计算', 'Signals'], ts_sync: ['库存同步', 'Synced'], ts_collector: ['采集器', 'Collector'], ts_running: ['运行中…', 'Running…'], ts_latest: ['最新', 'Latest'],
          changelog_title: ['更新日志', 'Changelog'], changelog_subtitle: ['项目版本更新记录', 'Project version history'], current_version: ['当前版本', 'Current Version'], cl_added: ['新增', 'Added'], cl_fixed: ['修复', 'Fixed'], cl_changed: ['变更', 'Changed'], cl_commits: ['提交记录', 'Commits'],
          status_rented: ['出租中', 'Rented'], status_steam: ['Steam中', 'In Steam'], status_storage: ['收藏', 'Storage'], status_sold: ['已售', 'Sold'], inv_value: ['库存市值', 'Inventory Value'], rented_value: ['出租市值', 'Rented Value'], covers: ['覆盖', 'Covers'], items_unit: ['件', 'items'], total_items: ['共', 'Total'], rented_value_note: ['出租市值基于市价快照计算，与悠悠官方估值可能略有差异', 'Rented value based on price snapshots, may differ slightly from YouPin official valuation'],
          search_placeholder: ['搜索饰品名称…', 'Search item name…'], all_status: ['全部状态', 'All Status'], all_types: ['全部类型', 'All Types'], all_filter: ['全部', 'All'], priced: ['已定价', 'Priced'], show_sold: ['显示已售', 'Show Sold'], dual_price: ['双价对比', 'Dual Price'], cost_sort: ['成本排序', 'Cost Sort'],
          th_item: ['饰品', 'Item'], th_status: ['状态', 'Status'], th_abrade: ['磨损', 'Wear'], th_cost: ['成本价', 'Cost'], th_auto_price: ['自动价', 'Auto'], th_manual_price: ['手动价', 'Manual'], th_market_price: ['市价', 'Market'], th_pnl: ['盈亏', 'P&L'], th_pnl_pct: ['涨跌%', 'Change%'], th_date: ['购入日期', 'Buy Date'], th_platform: ['平台', 'Platform'], th_daily_rent: ['日租金', 'Daily Rent'], th_deposit: ['押金', 'Deposit'], th_expire: ['到期时间', 'Expires'], th_renewal: ['续租', 'Renewal'], th_operation: ['操作', 'Actions'], th_market_ref: ['市场参考价', 'Market Ref'], th_market_ref_rent: ['市场参考租金', 'Market Ref Rent'], th_sell_price: ['出售价', 'Sell Price'],
          total_records: ['共', 'Total'], records_unit: ['条', ''], page_unit: ['页', ''], page_prefix: ['第', 'Page'], loading: ['加载中…', 'Loading…'], no_match: ['没有找到匹配的饰品', 'No matching items found'],
          panel_status: ['状态', 'Status'], panel_source: ['来源', 'Source'], panel_abrade: ['磨损值', 'Wear Value'], panel_buy_date: ['购入日期', 'Buy Date'], panel_buy_platform: ['购入平台', 'Platform'], panel_auto_price: ['自动识别价', 'Auto Price'], panel_effective: ['生效价格', 'Effective Price'], panel_first_seen: ['首次发现', 'First Seen'], manual_price_title: ['手动购入价', 'Manual Buy Price'], manual_price_set: ['已手动设置', 'Manually Set'], manual_price_desc: ['优先于自动识别价，不被自动导入覆盖。', 'Overrides auto price, not overwritten by import.'], btn_save: ['保存', 'Save'], btn_clear_manual: ['清除手动价格', 'Clear Manual Price'],
          shelf_sell: ['出售货架', 'Sell Shelf'], shelf_lease: ['出租货架', 'Lease Shelf'], shelf_rented: ['已租出', 'Rented Out'], shelf_sublet: ['转租中/0CD', 'Sublet/0CD'], shelf_unlisted: ['待上架', 'Unlisted'], btn_batch_delist: ['批量下架', 'Batch Delist'], btn_batch_reprice: ['批量智能改价', 'Smart Reprice'], btn_repricing: ['改价中…', 'Repricing…'], btn_reprice: ['改价', 'Reprice'], btn_delist: ['下架', 'Delist'], btn_cancel_sublet: ['取消转租', 'Cancel Sublet'], selected_count: ['已选', 'Selected'], clear_selection: ['清除选择', 'Clear'], shelf_empty: ['货架为空', 'Shelf is empty'], loading_shelf: ['加载货架…', 'Loading shelf…'], loading_data: ['加载中…', 'Loading…'], no_data: ['暂无数据，请点击「刷新」', 'No data, click refresh'],
          smart_listing_note: ['智能上架功能需先完成「同步数据」→「同步模板ID」以获取市场定价参考', 'Smart listing requires sync data + sync template IDs first'], need_list_note: ['需要上架新饰品？请切换到「待上架」标签页，从库存中选择饰品快速上架', 'To list new items, switch to the "Unlisted" tab'], shelf_empty_sync: ['货架为空，或尚未同步模板ID（用于市场定价）', 'Shelf empty, or template IDs not synced yet'], btn_sync_template: ['同步模板ID（用于市场定价）', 'Sync Template IDs'], syncing_text: ['同步中…', 'Syncing…'], on_sale: ['在售', 'Listed'], subletting: ['转租中', 'Subletting'],
          reprice_title: ['改价', 'Reprice'], sell_price_label: ['出售价（元）', 'Sell Price (¥)'], short_rent_label: ['短租日租金（元/天）', 'Daily Rent (¥/day)'], long_rent_label: ['长租日租金（元/天，可选）', 'Long-term Rent (¥/day, optional)'], deposit_label: ['押金（元）', 'Deposit (¥)'], long_rent_hint: ['留空则按短租价×0.95', 'Leave empty for short rent × 0.95'], btn_cancel: ['取消', 'Cancel'], btn_confirm_reprice: ['确认改价', 'Confirm'], saving_text: ['保存中…', 'Saving…'],
          login_title: ['悠悠有品 手机号登录', 'YouPin SMS Login'], login_desc: ['通过手机号+验证码获取 App 端 Token（支持上架/下架/改价等操作）', 'Get App token via phone + SMS code'], phone_label: ['手机号', 'Phone'], code_label: ['验证码', 'Code'], btn_send_code: ['发送验证码', 'Send Code'], sending_code: ['发送中…', 'Sending…'], btn_login: ['登录', 'Login'], logging_in: ['登录中…', 'Logging in…'], manual_token_desc: ['或直接粘贴 Token（从悠悠 App 或浏览器 DevTools 获取）', 'Or paste token directly (from YouPin App or DevTools)'], btn_apply: ['应用', 'Apply'],
          token_expired_msg: ['悠悠有品 Token 已过期，所有同步/上架功能不可用', 'YouPin token expired, sync/listing functions unavailable'], token_expired_hint: ['→ 登录 www.youpin898.com → DevTools → Network → 复制 Authorization header 中的 Bearer Token → 更新 .env 重启服务', '→ Login youpin898.com → DevTools → Copy Bearer Token → Update .env'],
          import_done: ['导入完成', 'Import Complete'], btn_refresh_data: ['刷新数据', 'Refresh Data'],
          analysis_overview: ['市场总览', 'Overview'], analysis_detail: ['饰品分析', 'Item Analysis'], analysis_alerts: ['预警中心', 'Alerts'], analysis_spreads: ['套利雷达', 'Arbitrage'], unread_alerts: ['未读预警', 'Unread Alerts'], avg_sell_score: ['平均卖出评分', 'Avg Sell Score'], avg_momentum_30: ['30D 平均动量', '30D Avg Momentum'], data_status: ['数据状态', 'Data Status'], collecting: ['采集中…', 'Collecting…'], last_run: ['上次', 'Last'], not_started: ['未启动', 'Not started'], signal_date: ['信号日期', 'Signal date'], no_signal: ['无信号数据', 'No signal data'],
          score_dist_title: ['卖出评分分布（持仓饰品）', 'Sell Score Distribution (Holdings)'], score_dist_hint: ['点击柱状查看详情', 'Click bar for details'], score_hold: ['持有', 'Hold'], score_neutral: ['中性', 'Neutral'], score_consider: ['考虑卖', 'Consider'], score_strong: ['强卖', 'Strong Sell'], score_urgent: ['急卖', 'Urgent'],
          top10_sell: ['Top 10 卖出信号', 'Top 10 Sell Signals'], category_trends: ['分类趋势', 'Category Trends'], btn_backfill: ['回填历史数据', 'Backfill History'], backfilling: ['回填中…', 'Backfilling…'], btn_compute: ['立即计算信号', 'Compute Signals'], computing: ['计算中…', 'Computing…'], btn_collect: ['立即采集价格', 'Collect Prices'],
          search_item_hint: ['搜索饰品名称…', 'Search item name…'], no_signal_hint: ['暂无信号数据，请先触发信号计算', 'No signal data, trigger computation first'], no_recommend: ['暂无推荐数据，请先触发信号计算', 'No recommendations, compute signals first'], recommend_hint: ['在上方搜索框输入饰品名称查看分析，或点击以下推荐饰品：', 'Search an item above, or click a recommendation:'],
          all_levels: ['全部级别', 'All Levels'], level_critical: ['严重', 'Critical'], level_warning: ['警告', 'Warning'], level_info: ['信息', 'Info'], all_types_alert: ['全部类型', 'All Types'], unread_only: ['仅未读', 'Unread Only'], btn_mark_all_read: ['全部已读', 'Mark All Read'], btn_read: ['已读', 'Read'], btn_view: ['查看', 'View'], no_alerts: ['暂无预警记录', 'No alerts'],
          min_spread: ['最小价差 %', 'Min Spread %'], no_arb_data: ['暂无套利数据', 'No arbitrage data'],
          sell_score_title: ['综合卖出评分', 'Sell Score'], buy_opp_title: ['买入机会评分', 'Buy Opportunity'], buy_opp_beta: ['β测试', 'β Test'], buy_opp_note: ['综合超卖(25%)、下轨(20%)、回调(15%)、价差(20%)、深亏增持(20%)', 'Oversold(25%), BB Low(20%), Dip(15%), Spread(20%), Loss Avg-down(20%)'],
          ownership_title: ['持仓信息', 'Ownership'], ownership_buy: ['购入价', 'Buy Price'], ownership_current: ['当前价', 'Current'], ownership_pnl: ['盈亏', 'P&L'], cross_platform: ['跨平台价格对比', 'Cross-Platform Prices'],
          sell_score_desc: ['CS2大商决策模型：收益达标度(30%)、年化收益衰减(20%)、持仓集中度(20%)、异常波动(25%)、市场冲击(5%) 加权计算。注意：暂未纳入租金年化收益率。', 'Dealer model: Target P&L(30%), Annual Return Decay(20%), Concentration(20%), Volatility Anomaly(25%), Market Impact(5%). Note: rental yield not included.'],
          sig_ann_return: ['年化收益', 'Ann. Return'], sig_holding_count: ['持有件数', 'Holding'], sig_concentration: ['持仓占比', 'Concentration'], sig_market_share: ['市场份额', 'Mkt Share'], sig_vol_zscore: ['波动Z值', 'Vol Z-Score'],
          label_hold: ['继续持有', 'Hold'], label_neutral: ['中性持有', 'Neutral'], label_consider: ['考虑出售', 'Consider Sell'], label_strong: ['强烈出售', 'Strong Sell'], label_urgent: ['立即出售', 'Sell Now'],
          rental_yield: ['租金年化率', 'Rental Yield'], rental_yield_desc: ['基于短租日租金估算。有效出租天数：普通188天/年，0CD 310天/年。年化率 = 有效天数 × 日租金 / 饰品价值 × 100%', 'Annualized rental yield. Effective days: normal 188/yr, 0CD 310/yr.'],
          mini_cost: ['总成本', 'Total Cost'], mini_active: ['活跃持仓', 'Active'], mini_coverage: ['定价覆盖', 'Coverage'], mini_manual: ['手动定价', 'Manual'],
          cat_knife: ['刀具', 'Knife'], cat_glove: ['手套', 'Glove'], cat_pistol: ['手枪', 'Pistol'], cat_rifle: ['步枪', 'Rifle'], cat_sniper: ['狙击', 'Sniper'], cat_smg: ['冲锋枪', 'SMG'], cat_shotgun: ['霰弹枪', 'Shotgun'], cat_mg: ['机枪', 'MG'], cat_sticker: ['印花', 'Sticker'], cat_case: ['箱子', 'Case'], cat_other: ['其他', 'Other'],
          unknown: ['未知', 'Unknown'], overbought: ['超买', 'Overbought'], oversold: ['超卖', 'Oversold'], neutral_rsi: ['中性', 'Neutral'], above_upper: ['突破上轨', 'Above Upper'], below_lower: ['低于下轨', 'Below Lower'], in_band: ['带内', 'In Band'], page_of: ['/', '/'],
    });

    function app() {
      return {
        activeTab: 'overview',
        trackerData: [],
        trackerMonthly: [],
        trackerLoading: false,
        trackerSnapshotting: false,
        _trackerChart: null,
        trackerChartType: 'combined_annual',
        trackerGranularity: 'daily',
        trackerShowAll: false,
        trackerVisibleRows: 30,
        overview: {},
        items: [],
        total: 0,
        loading: false,

        page: 1,
        pageSize: 50,
        filters: { search: '', status: '', pricedFilter: '', category: '' },
        sortBy: 'first_seen_at',
        sortOrder: 'desc',
        dualPrice: false,
        showSold: false,

        // 名称语言模式: 'cn'=中文优先 / 'en'=英文优先
        nameLang: localStorage.getItem('nameLang') || 'cn',
        theme: localStorage.getItem('theme') || 'dark',

        // 批量智能改价状态
        batchRepricing: false,
        batchRepriceProgress: '',

        // 出租大会员等级 (由 header select 控制)
        memberLevel: parseInt(localStorage.getItem('memberLevel') || '3'),
        // 悠悠大会员开关：开启后租金年化按310天计算，默认188天
        youpinMembership: localStorage.getItem('youpinMembership') !== 'false',

        // ── 量化分析 tab ──
        analysisTab: 'overview',
        ao: {},                      // analysis overview data
        itemSignals: null,           // selected item signals
        analysisAlerts: { items: [], total: 0 },
        analysisSpreads: { items: [], total: 0 },
        analysisSearch: '',
        analysisSearchResults: [],
        analysisTopItems: [],
        analysisSelectedItem: null,
        unreadAlertCount: 0,
        alertFilter: { severity: '', type: '', unreadOnly: false },
        alertPage: 1,
        minSpread: 5,
        chartDays: 0,
        scoreBucket: { show: false, label: '', min: 0, max: 0, items: [] },
        backfillRunning: false,
        backfillProgress: '',
        computingSignals: false,
        _priceChart: null,

        panel: null,
        manualInput: '',
        saving: false,

        importing: false,
        importProgress: -1,
        _progressTimer: null,
        importResult: null,
        lastImportAt: '',

        refreshing: false,
        refreshProgress: 0,
        _refreshPollTimer: null,
        _importPoll: null,

        tokenExpired: false,
        syncing: false,

        // Listing tab
        shelfTab: 'sell',
        shelfLoading: false,
        sellShelf: { items: [], total: 0 },
        leaseShelf: { items: [], total: 0 },
        // 成本基准调整
        _costAdjustOpen: false,
        _costAdjustVal: '',
        // 挂售快照
        snapshots: [],
        snapshotDetail: null,
        snapshotLoading: false,
        rentedList: { items: [], total: 0, stats: '', page_size: 50 },
        rentedLoading: false,
        rentedPage: 1,
        subletList: { items: [], total: 0, stats: '', page_size: 50 },
        subletLoading: false,
        subletPage: 1,
        unlistedItems: { items: [], total: 0, total_inventory: 0, total_listed: 0, page_size: 50 },
        unlistedLoading: false,
        unlistedPage: 1,
        repriceModal: { show: false, item: null, newPrice: '', newLeaseUnit: '', newLongLeaseUnit: '', newDeposit: '', saving: false },
        loginModal: { show: false, phone: '', code: '', sessionId: '', smsSending: false, logging: false, cooldown: 0, manualToken: '' },
        authState: { has_token: false, token_source: 'none', nickname: null },
        selectedItems: [],
        quickList: {
          assetId: '', templateId: null, mode: 'sell',
          buyPrice: 0, takeProfitRatio: 0, useUndercut: true,
          previewing: false, listing: false, preview: null,
        },

        changelogData: _CHANGELOG,

        // Portfolio trend chart
        portfolioRange: 'all',
        portfolioCategory: 'value',  // 'value' | 'rental'
        portfolioData: [],
        // _portfolioChart stored on canvas.__chart to avoid Alpine Proxy
        monitorStatus: {},

        // 涨跌色模式：'cn'=红涨绿跌（默认） 'us'=绿涨红跌
        colorMode: 'cn',

        _i18n: _I18N,


        // i18n helper: t('key') returns CN or EN string
        t(key) {
          const arr = this._i18n[key];
          if (!arr) return key;
          return this.nameLang === 'cn' ? arr[0] : arr[1];
        },

        toast: { msg: '', type: 'success' },

        // ── Computed page numbers ──────────────────────────────────────
        get pageNums() {
          const total = Math.max(1, Math.ceil(this.total / this.pageSize));
          const cur = this.page;
          if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
          if (cur <= 4) return [1, 2, 3, 4, 5, '...', total];
          if (cur >= total - 3) return [1, '...', total-4, total-3, total-2, total-1, total];
          return [1, '...', cur-1, cur, cur+1, '...', total];
        },

        // ── Init ──────────────────────────────────────────────────────
        async init() {
          const [,,, marketStatus, alertData] = await Promise.all([
            this.loadOverview(),
            this.loadItems(),
            this.loadPortfolioHistory(),
            fetch('/api/youpin/market/status').then(r => r.ok ? r.json() : null).catch(() => null),
            fetch('/api/analysis/alerts?page_size=1&unread_only=true').then(r => r.ok ? r.json() : null).catch(() => null),
            this._loadAuthState(),
            this._checkToken(),
          ]);
          if (marketStatus?.status === 'running') {
            this.refreshing = true;
            this.refreshProgress = marketStatus.progress;
            this._startRefreshPoll();
          }
          if (alertData) this.unreadAlertCount = alertData.total || 0;
          // Lazy-load tracker; re-render chart on every tab switch (canvas needs visible DOM)
          this.$watch('activeTab', (tab) => {
            if (tab === 'tracker' && this.trackerData.length === 0) this.loadTracker();
            // ApexCharts 在 display:none 容器中渲染宽度为0，切换 tab 后延迟重绘
            if (tab === 'overview') setTimeout(() => { try { this.renderPortfolioChart(); } catch(e) { console.warn('Portfolio chart error:', e); } }, 50);
            if (tab === 'tracker' && this.trackerData.length > 0) setTimeout(() => { try { this.renderTrackerChart(); } catch(e) { console.warn('Tracker chart error:', e); } }, 50);
          });
          // 持久化用户偏好到 localStorage
          this.$watch('nameLang', v => localStorage.setItem('nameLang', v));
          this.$watch('memberLevel', v => localStorage.setItem('memberLevel', v));
          this.$watch('youpinMembership', v => localStorage.setItem('youpinMembership', v));
          // Apply saved theme
          if (this.theme === 'light') document.documentElement.classList.add('light');
        },

        async _checkToken() {
          try {
            const r = await fetch('/api/youpin/token/status');
            if (r.ok) {
              const s = await r.json();
              this.tokenExpired = !s.valid;
              if (s.valid && s.nickname) this.authState.nickname = s.nickname;
              // 同步会员等级 → 自动开启大会员开关
              if (s.valid && s.member_level >= 2) {
                this.youpinMembership = true;
                localStorage.setItem('youpinMembership', 'true');
              }
            }
          } catch (e) { console.warn('Token check failed:', e.message); }
        },

        async _loadAuthState() {
          try {
            const r = await fetch('/api/youpin/auth/state');
            if (r.ok) {
              this.authState = await r.json();
              // 自动根据会员等级设置大会员开关（≥2 为大会员/黑金大会员）
              if (this.authState.member_level >= 2) {
                this.youpinMembership = true;
                localStorage.setItem('youpinMembership', 'true');
              }
            }
          } catch (e) { console.warn('Auth state load failed:', e.message); }
        },

        async sendSmsCode() {
          if (!this.loginModal.phone) return this.showToast('请输入手机号', 'error');
          this.loginModal.smsSending = true;
          try {
            const r = await fetch('/api/youpin/auth/send-sms', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ phone: this.loginModal.phone }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '发送失败');
            this.loginModal.sessionId = d.session_id;
            this.showToast('验证码已发送');
            // 60秒倒计时
            this.loginModal.cooldown = 60;
            const timer = setInterval(() => {
              this.loginModal.cooldown--;
              if (this.loginModal.cooldown <= 0) clearInterval(timer);
            }, 1000);
          } catch (e) {
            const msg = e.message || '';
            if (msg.includes('5050') || msg.includes('更新') || msg.includes('版本')) {
              this.showToast('悠悠有品 API 限制了第三方 SMS 登录。请在悠悠 App 中登录后，将 Token 填入 .env 文件的 YOUPIN_TOKEN 字段，或使用下方手动输入 Token 功能。', 'error');
            } else {
              this.showToast('发送失败：' + msg, 'error');
            }
          }
          finally { this.loginModal.smsSending = false; }
        },

        async applyManualToken() {
          const token = (this.loginModal.manualToken || '').trim();
          if (!token) return;
          try {
            const r = await fetch('/api/youpin/auth/apply-token', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ token }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Token 无效');
            this.showToast('Token 应用成功' + (d.nickname ? '：' + d.nickname : ''));
            this.loginModal.show = false;
            this.tokenExpired = false;
            await this._loadAuthState();
          } catch (e) {
            this.showToast('Token 无效：' + e.message, 'error');
          }
        },

        async doSmsLogin() {
          if (!this.loginModal.code || !this.loginModal.sessionId) return;
          this.loginModal.logging = true;
          try {
            const r = await fetch('/api/youpin/auth/login', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                phone: this.loginModal.phone,
                code: this.loginModal.code,
                session_id: this.loginModal.sessionId,
              }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '登录失败');
            this.showToast('登录成功：' + (d.nickname || ''));
            this.loginModal.show = false;
            this.tokenExpired = false;
            await this._loadAuthState();
          } catch (e) {
            this.showToast('登录失败：' + e.message, 'error');
          }
          finally { this.loginModal.logging = false; }
        },

        // ── 批量操作 ──────────────────────────────────────────────────
        toggleSelectItem(id) {
          const idx = this.selectedItems.indexOf(id);
          if (idx >= 0) this.selectedItems.splice(idx, 1);
          else this.selectedItems.push(id);
        },

        toggleSelectAll(items, key = 'commodityId') {
          const ids = items.map(i => i[key]).filter(Boolean);
          if (ids.every(id => this.selectedItems.includes(id))) {
            this.selectedItems = this.selectedItems.filter(id => !ids.includes(id));
          } else {
            const set = new Set(this.selectedItems);
            ids.forEach(id => set.add(id));
            this.selectedItems = [...set];
          }
        },

        async batchDelist() {
          if (!this.selectedItems.length || !confirm(`确认下架 ${this.selectedItems.length} 件物品？`)) return;
          try {
            const r = await fetch('/api/listing/batch-delist', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ commodity_ids: this.selectedItems }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '下架失败');
            this.showToast(`成功下架 ${this.selectedItems.length} 件（YouPin API 约需 30 秒更新库存，再刷新待上架）`);
            this.selectedItems = [];
            await this.loadShelf();
            // 3秒后自动刷新待上架列表（等待YouPin API同步延迟）
            setTimeout(() => { if (this.shelfTab === 'unlisted') this.loadUnlistedItems(1); }, 30000);
          } catch (e) { this.showToast('批量下架失败：' + e.message, 'error'); }
        },

        async batchDisableZeroCd() {
          if (!this.selectedItems.length || !confirm(`确认取消 ${this.selectedItems.length} 件转租？`)) return;
          try {
            const r = await fetch('/api/youpin/lease/disable-zero-cd', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ order_ids: this.selectedItems }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '取消失败');
            this.showToast('已取消 0CD 转租');
            this.selectedItems = [];
            await this.loadSubletList(this.subletPage);
          } catch (e) { this.showToast('批量取消失败：' + e.message, 'error'); }
        },

        get currentShelf() {
          return this.shelfTab === 'sell' ? (this.sellShelf.items || []) : (this.leaseShelf.items || []);
        },

        async loadAll() {
          await Promise.all([this.loadOverview(), this.loadItems(), this.loadPortfolioHistory(), this.loadMonitorStatus()]);
        },

        // ── Tracker ────────────────────────────────────────────────
        async loadTracker() {
          this.trackerLoading = true;
          try {
            const [dailyR, monthlyR] = await Promise.all([
              fetch('/api/tracker/daily'),
              fetch('/api/tracker/monthly?year=' + new Date().getFullYear()),
            ]);
            if (dailyR.ok) this.trackerData = await dailyR.json();
            if (monthlyR.ok) this.trackerMonthly = await monthlyR.json();
            this.$nextTick(() => {
              try { this.renderTrackerChart(); } catch(e) { console.warn('Chart render error:', e); }
              // 如果在概览页且选了租赁走势，也重绘
              if (this.activeTab === 'overview' && this.portfolioCategory === 'rental') {
                try { this.renderPortfolioChart(); } catch(e) { console.warn('Portfolio chart error:', e); }
              }
            });
          } catch (e) {
            this.showToast(e.message || 'Failed to load tracker data', 'error');
          } finally {
            this.trackerLoading = false;
          }
        },

        // 解析公式：支持 =3500+500 等基础运算
        parseFormula(input) {
          const s = String(input).trim();
          if (s.startsWith('=')) {
            const expr = s.slice(1);
            // 只允许数字、运算符、小数点、括号、空格
            if (!/^[\d+\-*/().e\s]+$/i.test(expr)) return NaN;
            try { return Function('"use strict"; return (' + expr + ')')(); }
            catch { return NaN; }
          }
          return parseFloat(s);
        },

        async trackerEditField(date, field, rawValue) {
          // 空字符串 → null（清除字段），否则解析公式
          const trimmed = (typeof rawValue === 'string') ? rawValue.trim() : rawValue;
          const value = (trimmed === '' || trimmed === null || trimmed === undefined)
            ? null
            : (typeof trimmed === 'string') ? this.parseFormula(trimmed) : trimmed;
          if (value !== null && isNaN(value)) {
            this.showToast('公式错误 / Invalid formula', 'error'); return;
          }
          try {
            const r = await fetch('/api/tracker/' + date, {
              method: 'PATCH',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ [field]: value }),
            });
            if (!r.ok) throw new Error('Update failed');
            // 用后端返回的完整行更新（含重算的派生字段）
            const updated = await r.json();
            const row = this.trackerData.find(d => d.date === date);
            if (row) Object.assign(row, updated);
          } catch (e) {
            this.showToast(e.message, 'error');
          }
        },

        async applyCostAdjust() {
          const raw = (this._costAdjustVal || '').trim();
          if (!raw) return;
          const delta = this.parseFormula(raw);
          if (isNaN(delta) || delta === 0) {
            this.showToast('请输入有效金额 / Invalid amount', 'error');
            return;
          }
          const current = Number(this.trackerData[0]?.cost_basis) || 0;
          const newBasis = current + delta;
          if (newBasis < 0) {
            this.showToast('成本不能为负 / Cost basis cannot be negative', 'error');
            return;
          }
          await this.trackerEditField(this.trackerData[0].date, 'cost_basis', newBasis);
          this._costAdjustOpen = false;
          this._costAdjustVal = '';
          const sign = delta > 0 ? '+' : '';
          this.showToast(`成本基准已更新 ${sign}${delta.toLocaleString()} → ¥${newBasis.toLocaleString()}`, 'success');
        },

        async trackerSnapshot() {
          this.trackerSnapshotting = true;
          try {
            const r = await fetch('/api/tracker/snapshot?is_vip=' + this.youpinMembership, { method: 'POST' });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Snapshot failed');
            this.showToast(this.nameLang==='cn'?'今日数据已刷新':'Today refreshed', 'success');
            await this.loadTracker();
          } catch (e) {
            this.showToast(e.message, 'error');
          } finally {
            this.trackerSnapshotting = false;
          }
        },

        async trackerImportExcel(ev) {
          const file = ev.target.files[0];
          if (!file) return;
          const form = new FormData();
          form.append('file', file);
          try {
            const r = await fetch('/api/tracker/import', { method: 'POST', body: form });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Import failed');
            this.showToast(`${this.nameLang==='cn'?'导入成功':'Imported'}: ${d.imported} ${this.nameLang==='cn'?'条':'records'}`, 'success');
            await this.loadTracker();
          } catch (e) {
            this.showToast(e.message, 'error');
          }
          ev.target.value = '';
        },

        renderTrackerChart() {
          const el = document.getElementById('trackerChart');
          if (!el) return;
          const fingerprint = this.trackerChartType + ':' + this.trackerData.length;
          if (el.__chart && el.__fingerprint === fingerprint) return;
          if (this._trackerChart) { this._trackerChart.destroy(); this._trackerChart = null; }
          el.__fingerprint = fingerprint;

          const key = this.trackerChartType;
          const isPct = ['combined_annual','short_lease_annual','long_lease_annual','price_change'].includes(key);
          const isMoney = ['daily_income','inventory_value','rented_value','market_value'].includes(key);
          const nameMap = { combined_annual:'综合年化', daily_income:'日租金', inventory_value:'库存价值', price_change:'涨跌', short_lease_annual:'短租年化', long_lease_annual:'长租年化', rented_value:'出租价值', market_value:'总市值' };
          const label = this.nameLang === 'cn' ? (nameMap[key] || key) : key.replace(/_/g,' ');
          const fmtY = v => v == null ? '' : isPct ? v.toFixed(1)+'%' : isMoney ? (v>=1e4?'¥'+(v/1e4).toFixed(1)+'万':'¥'+v.toFixed(0)) : v;
          const fmtTip = v => v == null ? '—' : isPct ? v.toFixed(2)+'%' : isMoney ? '¥'+Number(v).toLocaleString() : v;

          let series, chartHeight = 200;

          if (this.trackerGranularity === 'hourly' && this.portfolioData.length) {
            // 时模式：用 portfolio_snapshot 数据（30分钟粒度）
            // 映射 trackerChartType → portfolio_snapshot 字段
            const fieldMap = { inventory_value: 'market_value', market_value: 'market_value', combined_annual: 'pnl_pct', price_change: 'pnl_pct', daily_income: 'pnl', rented_value: 'rented_out_value' };
            const pKey = fieldMap[key] || 'market_value';
            const pIsPct = ['pnl_pct'].includes(pKey);
            series = this.portfolioData.map(d => {
              const dt = new Date(d.timestamp);
              const lbl = dt.toLocaleString('en-US', { timeZone:'America/Los_Angeles', month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false });
              const v = d[pKey];
              return { x: lbl, y: v != null ? (pIsPct ? +Number(v).toFixed(2) : +Number(v).toFixed(2)) : null };
            });
            chartHeight = 240;
          } else {
            // 日模式：用 daily_tracker 数据
            if (!this.trackerData?.length) return;
            const data = [...this.trackerData].reverse();
            series = data.map(d => {
              const v = d[key];
              return { x: d.date.slice(5), y: v != null ? (isPct ? +(v * 100).toFixed(2) : +Number(v).toFixed(2)) : null };
            });
          }

          this._trackerChart = new ApexCharts(el, {
            chart: { type: 'area', height: chartHeight, background: 'transparent',
              toolbar: { show: true, offsetY: -5, tools: { download: false, selection: false, zoom: true, zoomin: true, zoomout: true, pan: true, reset: true } },
              zoom: { enabled: true, type: 'x', autoScaleYaxis: true },
              fontFamily: 'ui-monospace, monospace',
            },
            series: [{ name: label, data: series }],
            stroke: { curve: 'smooth', width: 2 },
            fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.25, opacityTo: 0.02 } },
            colors: ['#3b82f6'],
            dataLabels: { enabled: false },
            xaxis: { type: 'category', labels: { style: { colors: '#64748b', fontSize: '10px' }, rotate: 0, hideOverlappingLabels: true }, tickAmount: 10, axisBorder: { show: false }, axisTicks: { show: false } },
            yaxis: { labels: { style: { colors: '#64748b', fontSize: '10px' }, formatter: fmtY } },
            grid: { borderColor: 'rgba(51,65,85,0.2)', strokeDashArray: 3, padding: { left: 5, right: 5 } },
            tooltip: { theme: 'dark', y: { formatter: fmtTip } },
            theme: { mode: 'dark' },
          });
          this._trackerChart.render();

          // 滚轮缩放 X 轴
          this.$nextTick(() => {
            const chartEl = el.querySelector('.apexcharts-canvas');
            if (!chartEl) return;
            chartEl.addEventListener('wheel', (e) => {
              e.preventDefault();
              const g = this._trackerChart.w.globals;
              const min = g.minX, max = g.maxX, total = g.dataPoints;
              const range = max - min;
              if (range <= 0) return;
              const factor = e.deltaY > 0 ? 0.15 : -0.15;
              let newMin = Math.round(min + range * factor);
              let newMax = Math.round(max - range * factor);
              newMin = Math.max(0, newMin);
              newMax = Math.min(total - 1, newMax);
              if (newMax - newMin >= 5) this._trackerChart.zoomX(newMin, newMax);
            }, { passive: false });
          });
        },

        async loadOverview() {
          try {
            const r = await fetch('/api/dashboard/overview');
            if (r.ok) this.overview = await r.json();
          } catch (e) { this.showToast(e.message || '加载概览失败', 'error'); }
        },

        // ── Portfolio Trend Chart ──────────────────────────────────────
        async loadPortfolioHistory() {
          try {
            const r = await fetch(`/api/monitoring/portfolio-history?range=${this.portfolioRange}`);
            if (!r.ok) return;
            const d = await r.json();
            this.portfolioData = d.data || [];
            if (this.activeTab === 'overview') setTimeout(() => { try { this.renderPortfolioChart(); } catch(e) { console.warn('Portfolio chart error:', e); } }, 50);
          } catch (e) { this.showToast(e.message || '加载持仓历史失败', 'error'); }
        },

        renderPortfolioChart() {
          const canvas = document.getElementById('portfolioChart');
          if (!canvas) return;
          const fingerprint = this.portfolioCategory + ':' + (this.portfolioCategory === 'value' ? this.portfolioData.length : this.trackerData.length);
          if (canvas.__chart && canvas.__fingerprint === fingerprint) return;
          if (canvas.__chart) { canvas.__chart.destroy(); canvas.__chart = null; }
          canvas.__fingerprint = fingerprint;
          const ctx = canvas.getContext('2d');
          if (!ctx) return;

          const fmtMoney = v => { if (v == null) return ''; const a = Math.abs(v); const s = v < 0 ? '-' : ''; return s + '¥' + (a >= 1e4 ? (a/1e4).toFixed(1)+'万' : a.toLocaleString()); };
          const fmtPct = v => v == null ? '' : v.toFixed(2) + '%';
          const gridColor = 'rgba(51,65,85,0.2)';
          const tickColor = '#64748b';

          if (this.portfolioCategory === 'value') {
            // ── 组合价值：左Y金额，右Y百分比 ──
            const data = this.portfolioData;
            if (!data.length) return;
            const labels = data.map(d => {
              const dt = new Date(d.timestamp);
              return dt.toLocaleString('en-US', { timeZone:'America/Los_Angeles', month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false });
            });
            canvas.__chart = new Chart(ctx, {
              type: 'line',
              data: {
                labels,
                datasets: [
                  { label: this.t('market_value'), data: data.map(d => d.market_value), yAxisID: 'yMoney', borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.08)', fill: true, borderWidth: 2.5, pointRadius: 0, tension: 0.3, order: 1 },
                  { label: this.t('total_cost'), data: data.map(d => d.total_cost), yAxisID: 'yMoney', borderColor: '#3b82f6', borderDash: [6,3], borderWidth: 2, pointRadius: 0, tension: 0.3, fill: false, order: 2 },
                  { label: this.t('pnl_amount'), data: data.map(d => d.pnl), yAxisID: 'yMoney', borderColor: '#f59e0b', borderDash: [4,2], borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: false, order: 3 },
                  { label: this.t('chart_pnl_pct'), data: data.map(d => d.pnl_pct), yAxisID: 'yPct', borderColor: '#ef4444', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: false, order: 4 },
                ],
              },
              options: {
                responsive: true, maintainAspectRatio: false, resizeDelay: 100, animation: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                  legend: { position: 'top', align: 'start', labels: { color: '#94a3b8', font: { size: 11, family: 'ui-monospace, monospace' }, usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 8, padding: 12 } },
                  tooltip: { backgroundColor: 'rgba(15,23,42,0.95)', titleColor: '#e2e8f0', bodyColor: '#cbd5e1', borderColor: 'rgba(51,65,85,0.5)', borderWidth: 1, padding: 10, bodyFont: { family: 'ui-monospace, monospace', size: 11 },
                    callbacks: { label: ctx => { const v = ctx.raw; return ctx.dataset.label + ': ' + (ctx.datasetIndex === 3 ? fmtPct(v) : fmtMoney(v)); } },
                  },
                },
                scales: {
                  x: { ticks: { color: tickColor, font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { color: gridColor, drawBorder: false } },
                  yMoney: { position: 'left', ticks: { color: tickColor, font: { size: 10 }, callback: fmtMoney }, grid: { color: gridColor, drawBorder: false } },
                  yPct: { position: 'right', ticks: { color: '#ef4444', font: { size: 10 }, callback: v => fmtPct(v) }, grid: { drawOnChartArea: false } },
                },
              },
            });
          } else {
            // ── 租赁走势：左Y百分比，右Y金额 ──
            const data = [...this.trackerData].reverse();
            if (!data.length) return;
            const labels = data.map(d => d.date);
            canvas.__chart = new Chart(ctx, {
              type: 'line',
              data: {
                labels,
                datasets: [
                  { label: this.t('tracker_col_combined'), data: data.map(d => d.combined_annual != null ? +(d.combined_annual * 100).toFixed(2) : null), yAxisID: 'yPct', borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.08)', fill: true, borderWidth: 2.5, pointRadius: 0, tension: 0.3, order: 1 },
                  { label: this.t('tracker_col_income'), data: data.map(d => d.daily_income), yAxisID: 'yRight', borderColor: '#f59e0b', borderWidth: 2, pointRadius: 0, tension: 0.3, fill: false, order: 2 },
                  { label: this.t('tracker_col_rented'), data: data.map(d => d.rented_count), yAxisID: 'yRight', borderColor: '#3b82f6', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: false, order: 3 },
                  { label: this.t('chart_rented_value'), data: data.map(d => d.rented_value), yAxisID: 'yValue', borderColor: '#ec4899', borderDash: [6,3], borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: false, order: 4 },
                ],
              },
              options: {
                responsive: true, maintainAspectRatio: false, resizeDelay: 100, animation: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                  legend: { position: 'top', align: 'start', labels: { color: '#94a3b8', font: { size: 11, family: 'ui-monospace, monospace' }, usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 8, padding: 12 } },
                  tooltip: { backgroundColor: 'rgba(15,23,42,0.95)', titleColor: '#e2e8f0', bodyColor: '#cbd5e1', borderColor: 'rgba(51,65,85,0.5)', borderWidth: 1, padding: 10, bodyFont: { family: 'ui-monospace, monospace', size: 11 },
                    callbacks: { label: ctx => { const v = ctx.raw; const i = ctx.datasetIndex; return ctx.dataset.label + ': ' + (i === 0 ? fmtPct(v) : i === 2 ? (v??0)+' 件' : fmtMoney(v)); } },
                  },
                },
                scales: {
                  x: { ticks: { color: tickColor, font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { color: gridColor, drawBorder: false } },
                  yPct: { position: 'left', ticks: { color: '#10b981', font: { size: 10 }, callback: v => fmtPct(v) }, grid: { color: gridColor, drawBorder: false } },
                  yRight: { position: 'right', ticks: { color: '#f59e0b', font: { size: 10 }, callback: fmtMoney }, grid: { drawOnChartArea: false } },
                  yValue: { display: false },
                },
              },
            });
          }
        },

        // ── System Monitor ─────────────────────────────────────────────
        async loadMonitorStatus() {
          try {
            const r = await fetch('/api/monitoring/status');
            if (r.ok) this.monitorStatus = await r.json();
          } catch (e) { this.showToast(e.message || '加载监控状态失败', 'error'); }
        },

        async loadItems() {
          this.loading = true;
          try {
            const p = new URLSearchParams({
              page: this.page,
              page_size: this.pageSize,
              sort_by: this.sortBy,
              sort_order: this.sortOrder,
            });
            if (this.filters.search)        p.set('search', this.filters.search);
            if (this.filters.status)        p.set('status', this.filters.status);
            if (this.filters.pricedFilter)  p.set('priced_filter', this.filters.pricedFilter);
            if (this.filters.category)      p.set('category', this.filters.category);
            if (!this.showSold)             p.set('exclude_sold', '1');
            const r = await fetch('/api/dashboard/items?' + p);
            if (r.ok) { const d = await r.json(); this.items = d.items; this.total = d.total; }
          } catch (e) { this.showToast(e.message || '加载物品列表失败', 'error'); }
          finally { this.loading = false; }
        },

        // ── Pagination ────────────────────────────────────────────────
        gotoPage(p) {
          const max = Math.ceil(this.total / this.pageSize);
          if (p < 1 || p > max) return;
          this.page = p;
          this.loadItems();
          document.querySelector('.tbl-wrap')?.scrollTo({ top: 0, behavior: 'smooth' });
        },

        // ── Sort ──────────────────────────────────────────────────────
        setSort(col) {
          if (this.sortBy === col) this.sortOrder = this.sortOrder === 'asc' ? 'desc' : 'asc';
          else { this.sortBy = col; this.sortOrder = 'desc'; }
          this.page = 1;
          this.loadItems();
        },
        sortIcon(col) {
          if (this.sortBy !== col) return '↕';
          return this.sortOrder === 'asc' ? '↑' : '↓';
        },

        // ── Detail panel ──────────────────────────────────────────────
        openPanel(item) {
          this.panel = { ...item };
          this.manualInput = item.purchase_price_manual != null ? item.purchase_price_manual : '';
        },

        panelFields() {
          if (!this.panel) return [];
          const p = this.panel;
          const eff = p.effective_price != null ? '¥' + this.fmt(p.effective_price) : null;
          const auto = p.purchase_price != null ? '¥' + this.fmt(p.purchase_price) : null;
          const date = p.first_seen_at ? new Date(p.first_seen_at).toLocaleString('zh-CN', { timeZone: 'America/Los_Angeles' }) : null;
          return [
            [this.t('panel_status'),     this.statusLbl(p.status),  false, false],
            [this.t('panel_source'),     p.class_id,                 false, false],
            [this.t('panel_abrade'),     p.abrade?.toFixed(10),      true,  false],
            [this.t('panel_buy_date'),   p.purchase_date,            false, false],
            [this.t('panel_buy_platform'), p.purchase_platform,      false, false],
            [this.t('panel_auto_price'), auto,                        false, false],
            [this.t('panel_effective'),  eff, false, p.purchase_price_manual != null],
            [this.t('panel_first_seen'), date,                        true,  false],
          ];
        },

        async saveManual() {
          if (!this.panel) return;
          this.saving = true;
          try {
            const price = this.manualInput !== '' && this.manualInput !== null
              ? parseFloat(this.manualInput) : null;
            const r = await fetch(`/api/dashboard/items/${this.panel.id}/manual-price`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ price }),
            });
            if (!r.ok) throw new Error();
            const upd = await r.json();
            this.panel.purchase_price_manual = upd.purchase_price_manual;
            this.panel.effective_price = upd.effective_price;
            const row = this.items.find(i => i.id === this.panel.id);
            if (row) { row.purchase_price_manual = upd.purchase_price_manual; row.effective_price = upd.effective_price; }
            this.showToast('保存成功 ✓');
            await this.loadOverview();
          } catch { this.showToast('保存失败', 'error'); }
          finally { this.saving = false; }
        },

        async clearManual() {
          this.manualInput = '';
          await this.saveManual();
        },

        // ── Price Refresh ──────────────────────────────────────────────
        async triggerRefreshPrices() {
          if (this.refreshing) return;
          this.refreshing = true;
          this.refreshProgress = 0;
          try {
            const r = await fetch('/api/dashboard/refresh-prices', { method: 'POST' });
            if (!r.ok) throw new Error(await r.text());
            const d = await r.json();
            if (!d.started && d.state?.status !== 'running') {
              this.showToast('启动失败', 'error');
              this.refreshing = false;
              return;
            }
            this._startRefreshPoll();
          } catch (e) {
            this.refreshing = false;
            this.showToast('刷新启动失败：' + e.message, 'error');
          }
        },

        _startRefreshPoll() {
          clearInterval(this._refreshPollTimer);
          this._refreshPollTimer = setInterval(async () => {
            try {
              const r = await fetch('/api/youpin/market/status');
              if (!r.ok) return;
              const s = await r.json();
              this.refreshProgress = s.progress;
              if (s.status === 'done' || s.status === 'error' || s.status === 'token_expired') {
                clearInterval(this._refreshPollTimer);
                this.refreshing = false;
                if (s.status === 'done') {
                  this.showToast('市价刷新完成 ✓');
                  await this.loadAll();
                } else if (s.status === 'token_expired') {
                  this.tokenExpired = true;
                  this.showToast('Token 已过期，市价刷新中断', 'error');
                } else {
                  this.showToast('市价刷新失败：' + (s.error || '未知错误'), 'error');
                }
              }
            } catch (e) { this.showToast(e.message || '刷新轮询失败', 'error'); }
          }, 2500);
        },

        // ── Listing tab ───────────────────────────────────────────────────
        // ── 挂售快照 ──────────────────────────────────────────────────
        async loadSnapshots() {
          try {
            const r = await fetch('/api/listing/snapshots');
            if (r.ok) this.snapshots = await r.json();
          } catch (e) { this.showToast(e.message || '加载快照失败', 'error'); }
        },
        async createSnapshot(shelfType) {
          this.snapshotLoading = true;
          try {
            const r = await fetch('/api/listing/snapshot', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ shelf_type: shelfType }),
            });
            if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || '保存失败'); }
            const data = await r.json();
            this.showToast(`快照已保存: ${data.item_count}件, ¥${data.total_value?.toLocaleString()}`, 'success');
            await this.loadSnapshots();
          } catch (e) { this.showToast(e.message || '保存快照失败', 'error'); }
          finally { this.snapshotLoading = false; }
        },
        async loadSnapshotDetail(id) {
          try {
            const r = await fetch(`/api/listing/snapshot/${id}`);
            if (r.ok) this.snapshotDetail = await r.json();
          } catch (e) { this.showToast(e.message || '加载快照详情失败', 'error'); }
        },
        async deleteSnapshot(id) {
          if (!confirm(this.nameLang === 'cn' ? '确定删除该快照？' : 'Delete this snapshot?')) return;
          try {
            const r = await fetch(`/api/listing/snapshot/${id}`, { method: 'DELETE' });
            if (r.ok) {
              this.snapshots = this.snapshots.filter(s => s.id !== id);
              if (this.snapshotDetail?.id === id) this.snapshotDetail = null;
              this.showToast('快照已删除', 'success');
            }
          } catch (e) { this.showToast(e.message || '删除失败', 'error'); }
        },

        async loadShelf(which) {
          this.shelfLoading = true;
          try {
            const tab = which || this.shelfTab;
            if (tab === 'sell' || !which) {
              const sr = await fetch('/api/listing/shelf/sell?page_size=100');
              if (sr.ok) this.sellShelf = await sr.json();
            }
            if (tab === 'lease' || !which) {
              const lr = await fetch('/api/listing/shelf/lease?page_size=100');
              if (lr.ok) this.leaseShelf = await lr.json();
            }
          } catch (e) { this.showToast(e.message || '加载上架列表失败', 'error'); }
          finally { this.shelfLoading = false; }
        },

        async loadRentedList(page = 1) {
          this.rentedLoading = true;
          this.rentedPage = page;
          try {
            const p = new URLSearchParams({ page, page_size: 50 });
            const r = await fetch('/api/youpin/lease/live-list?' + p);
            if (r.ok) this.rentedList = await r.json();
          } catch (e) { this.showToast(e.message || '加载租赁列表失败', 'error'); }
          finally { this.rentedLoading = false; }
        },

        async loadSubletList(page = 1) {
          this.subletLoading = true;
          this.subletPage = page;
          try {
            const p = new URLSearchParams({ page, page_size: 50 });
            const r = await fetch('/api/youpin/lease/sublet-list?' + p);
            if (r.ok) this.subletList = await r.json();
          } catch (e) { this.showToast(e.message || '加载转租列表失败', 'error'); }
          finally { this.subletLoading = false; }
        },

        async loadUnlistedItems(page = 1) {
          this.unlistedLoading = true;
          this.unlistedPage = page;
          try {
            const p = new URLSearchParams({ page, page_size: 50 });
            const r = await fetch('/api/listing/shelf/unlisted?' + p);
            if (r.ok) this.unlistedItems = await r.json();
          } catch (e) { this.showToast(e.message || '加载未上架物品失败', 'error'); }
          finally { this.unlistedLoading = false; }
        },

        async cancelSubletOrder(orderId) {
          if (!orderId || !confirm('确认取消该饰品的0CD转租？')) return;
          try {
            const r = await fetch('/api/youpin/lease/disable-zero-cd', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ order_ids: [orderId] }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '取消失败');
            this.showToast('已取消0CD转租');
            await this.loadSubletList(this.subletPage);
          } catch (e) {
            this.showToast('取消失败：' + e.message, 'error');
          }
        },

        openReprice(item) {
          this.repriceModal = {
            show: true, item,
            newPrice: item.price ?? '',
            newLeaseUnit: item.leaseUnitPrice ?? '',
            newLongLeaseUnit: item.longLeasePrice ?? '',
            newDeposit: item.leaseDeposit ?? '',
            saving: false,
            isSublet: false,
          };
        },

        // 转租中物品改价（强制 lease 模式，不依赖 shelfTab）
        openSubletReprice(item) {
          this.repriceModal = {
            show: true, item,
            newPrice: '',
            newLeaseUnit: item.leaseUnitPrice ?? '',
            newLongLeaseUnit: item.longLeasePrice ?? '',
            newDeposit: item.leaseDeposit ?? '',
            saving: false,
            isSublet: true,
          };
        },

        // 查询货架物品的市场参考价（按需，点击「查」按钮触发）
        async fetchShelfMktPrice(item) {
          if (!item.templateId || item._mktLoading) return;
          item._mktLoading = true;
          // 强制 Alpine 重新渲染
          this.sellShelf = { ...this.sellShelf };
          this.leaseShelf = { ...this.leaseShelf };
          try {
            const p = new URLSearchParams({ template_id: item.templateId });
            if (item.abrade != null) p.set('abrade', item.abrade);
            const r = await fetch('/api/youpin/market/price-info?' + p);
            if (!r.ok) {
              const err = await r.json().catch(() => ({}));
              throw new Error(err.detail || `查询失败 (${r.status})`);
            }
            const d = await r.json();
            item._mktSell = d.suggested_sell;
            item._mktLease = d.suggested_lease;
          } catch (e) {
            item._mktSell = null;
            item._mktLease = null;
            this.showToast('市价查询失败：' + e.message, 'error');
          } finally {
            item._mktLoading = false;
            // 触发重新渲染
            this.sellShelf = { ...this.sellShelf };
            this.leaseShelf = { ...this.leaseShelf };
          }
        },

        // 批量智能改价：对选中货架物品按市场价改价
        async batchSmartReprice() {
          const shelf = this.currentShelf;
          const selected = shelf.filter(i => this.selectedItems.includes(i.commodityId));
          if (!selected.length) return;
          if (selected.some(i => !i.templateId)) {
            this.showToast('部分物品缺少模板ID，无法智能改价（请先同步模板ID）', 'error');
            return;
          }
          if (!confirm(`确认对 ${selected.length} 件物品按市场价智能改价？`)) return;

          this.batchRepricing = true;
          const isLease = this.shelfTab === 'lease';
          const items = selected.map(i => ({
            commodity_id: i.commodityId,
            template_id: i.templateId,
            abrade: i.abrade,
            is_can_lease: isLease,
          }));

          try {
            this.batchRepriceProgress = `0/${items.length}`;
            const r = await fetch('/api/listing/batch-smart-reprice', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ items, use_undercut: true }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '批量改价失败');
            this.showToast(`批量改价完成：${d.ok_count}/${d.total} 件成功`);
            this.selectedItems = [];
            await this.loadShelf();
          } catch (e) {
            this.showToast('批量改价失败：' + e.message, 'error');
          } finally {
            this.batchRepricing = false;
            this.batchRepriceProgress = '';
          }
        },

        async saveReprice() {
          const { item, newPrice, newLeaseUnit, newLongLeaseUnit, newDeposit } = this.repriceModal;
          if (!item || !item.commodityId) return;
          const isLease = this.shelfTab === 'lease' || this.repriceModal.isSublet;
          if (!isLease) {
            const p = parseFloat(newPrice);
            if (isNaN(p) || p <= 0) { this.showToast('请输入有效价格', 'error'); return; }
          }
          this.repriceModal.saving = true;
          try {
            const body = {
              commodity_id: item.commodityId,
              is_can_sold: !isLease,
              is_can_lease: isLease,
              ...(isLease
                ? { lease_unit: parseFloat(newLeaseUnit), long_lease_unit: parseFloat(newLongLeaseUnit) || undefined, deposit: parseFloat(newDeposit) }
                : { sell_price: parseFloat(newPrice) }),
            };
            const r = await fetch('/api/listing/reprice', {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(body),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '改价失败');
            this.showToast('改价成功');
            this.repriceModal.show = false;
            await this.loadShelf();
          } catch (e) {
            this.showToast('改价失败：' + e.message, 'error');
          }
          finally { this.repriceModal.saving = false; }
        },

        // 涨跌颜色：val为正/负，返回 Tailwind class
        pnlClass(val) {
          const up = val >= 0;
          if (this.colorMode === 'cn') return up ? 'text-red-400' : 'text-emerald-400';
          return up ? 'text-emerald-400' : 'text-red-400';
        },
        pnlClassMd(val) {
          const up = val >= 0;
          if (this.colorMode === 'cn') return up ? 'text-red-600' : 'text-emerald-600';
          return up ? 'text-emerald-600' : 'text-red-600';
        },
        pnlBg(val) {
          const up = val >= 0;
          if (this.colorMode === 'cn') return up ? 'rgba(239,68,68,0.07)' : 'rgba(16,185,129,0.07)';
          return up ? 'rgba(16,185,129,0.07)' : 'rgba(239,68,68,0.07)';
        },

        async syncTemplateIds() {
          this.syncing = true;
          try {
            const r = await fetch('/api/youpin/sync/template-ids', { method: 'POST' });
            if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Sync failed'); }
            // Poll status until done
            await new Promise((resolve) => {
              const poll = setInterval(async () => {
                try {
                  const sr = await fetch('/api/youpin/sync/template-ids/status');
                  const st = await sr.json();
                  if (st.status === 'done') {
                    clearInterval(poll);
                    const d = st.result || {};
                    this.showToast(`模板ID同步完成：更新 ${d.synced||0} 件，映射 ${d.unique_names_mapped||0} 个品类`);
                    resolve();
                  } else if (st.status === 'error') {
                    clearInterval(poll);
                    this.showToast((this.nameLang==='cn'?'同步失败: ':'Sync failed: ') + (st.error||''), 'error');
                    resolve();
                  }
                } catch (e) { console.warn('Template ID sync poll error:', e.message); }
              }, 2000);
              setTimeout(() => { clearInterval(poll); resolve(); }, 5 * 60 * 1000);
            });
          } catch (e) {
            this.showToast((this.nameLang==='cn'?'同步失败: ':'Sync failed: ') + e.message, 'error');
          }
          finally { this.syncing = false; }
        },

        async delistItem(commodityId) {
          if (!commodityId || !confirm('确认下架该物品？')) return;
          try {
            const r = await fetch(`/api/listing/${commodityId}`, { method: 'DELETE' });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '下架失败');
            this.showToast('下架成功（YouPin API 约需 30 秒更新库存，请稍后刷新待上架列表）');
            await this.loadShelf();
            // 5秒后刷新待上架列表
            setTimeout(() => { if (this.shelfTab === 'unlisted') this.loadUnlistedItems(1); }, 30000);
          } catch (e) {
            this.showToast('下架失败：' + e.message, 'error');
          }
        },

        async previewListPrice() {
          if (!this.quickList.templateId) return;
          this.quickList.previewing = true;
          try {
            const p = new URLSearchParams({
              template_id: this.quickList.templateId,
              buy_price: this.quickList.buyPrice || 0,
              take_profit_ratio: this.quickList.takeProfitRatio || 0,
            });
            if (this.quickList.abrade) p.set('abrade', this.quickList.abrade);
            const r = await fetch('/api/listing/preview?' + p);
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '预览失败');
            this.quickList.preview = d;
          } catch (e) {
            this.showToast('预览失败：' + e.message, 'error');
          }
          finally { this.quickList.previewing = false; }
        },

        async smartListItem() {
          if (!this.quickList.assetId || !this.quickList.templateId) return;
          const bp = parseFloat(this.quickList.buyPrice);
          const tpr = parseFloat(this.quickList.takeProfitRatio);
          if (isNaN(bp) || bp <= 0) { this.showToast('请输入有效的购入价格', 'error'); return; }
          if (isNaN(tpr) || tpr < 0) { this.showToast('请输入有效的止盈比例', 'error'); return; }
          this.quickList.listing = true;
          try {
            const r = await fetch('/api/listing/smart', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                asset_id: this.quickList.assetId,
                template_id: this.quickList.templateId,
                mode: this.quickList.mode,
                buy_price: this.quickList.buyPrice || 0,
                take_profit_ratio: this.quickList.takeProfitRatio || 0,
                use_undercut: this.quickList.useUndercut,
                member_level: this.memberLevel,
              }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '上架失败');
            if (d.ok) {
              const priceInfo = d.sell_price ? `出售价 ¥${this.fmt(d.sell_price)}` : `租金 ¥${this.fmt(d.lease_info?.lease_unit)}/天`;
              this.showToast(`上架成功 ${priceInfo}`);
              this.quickList.assetId = '';
              await this.loadShelf();
            } else {
              this.showToast(d.error || '上架失败', 'error');
            }
          } catch (e) {
            this.showToast('上架失败：' + e.message, 'error');
          }
          finally { this.quickList.listing = false; }
        },

        // ── Import ────────────────────────────────────────────────────
        async triggerImport(mode = 'quick') {
          this.importing = true;
          this.importProgress = 0;

          const endpoint = mode === 'records' ? '/api/youpin/import/records'
                         : mode === 'all'     ? '/api/youpin/import/all'
                         :                      '/api/youpin/import/quick';

          try {
            // 1) Fire-and-forget: start background import
            const r = await fetch(endpoint, { method: 'POST' });
            if (!r.ok) throw new Error(await r.text());
            const start = await r.json();
            if (start.started === false && start.state?.status !== 'running') {
              this.showToast(start.message || 'Import busy', 'error');
              this.importing = false;
              return;
            }

            // 2) Poll /import/status every 2s until done/error
            await new Promise((resolve, reject) => {
              clearInterval(this._importPoll);
              this._importPoll = setInterval(async () => {
                try {
                  const sr = await fetch('/api/youpin/import/status');
                  const st = await sr.json();
                  // progress bar: dynamic based on total_steps
                  const total = st.total_steps || 4;
                  const stepPct = 100 / total;
                  const base = (st.completed || []).length * stepPct;
                  this.importProgress = Math.min(base + stepPct * 0.4, 95);

                  if (st.status === 'done') {
                    clearInterval(this._importPoll);
                    this.importProgress = 100;
                    setTimeout(() => { this.importProgress = -1; }, 700);
                    this.importResult = st.results;
                    this.lastImportAt = new Date().toLocaleTimeString('zh-CN', { timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit' });
                    await this.loadAll();
                    resolve();
                  } else if (st.status === 'error') {
                    clearInterval(this._importPoll);
                    this.importProgress = -1;
                    this.showToast((this.nameLang==='cn'?'导入出错: ':'Import error: ') + (st.error || 'unknown'), 'error');
                    resolve();
                  }
                } catch (pe) {
                  console.warn('Import poll network error:', pe.message);
                }
              }, 2000);

              // safety timeout: 15 minutes
              setTimeout(() => {
                clearInterval(this._importPoll);
                this.importProgress = -1;
                this.showToast(this.nameLang==='cn'?'导入超时，请刷新页面查看':'Import timeout, refresh page', 'error');
                resolve();
              }, 15 * 60 * 1000);
            });
          } catch (e) {
            this.importProgress = -1;
            this.showToast((this.nameLang==='cn'?'导入失败: ':'Import failed: ') + e.message, 'error');
          } finally {
            this.importing = false;
          }
        },

        // ── 量化分析 ───────────────────────────────────────────────────

        async loadAnalysis() {
          try {
            const r = await fetch('/api/analysis/overview');
            if (r.ok) this.ao = await r.json();
            this.unreadAlertCount = this.ao.unread_alerts || 0;
          } catch (e) { this.showToast(e.message || '加载分析概览失败', 'error'); }
        },

        loadAnalysisSubTab(tab) {
          if (tab === 'overview') this.loadAnalysis();
          else if (tab === 'detail') this.loadTopItems();
          else if (tab === 'alerts') this.loadAlerts(1);
          else if (tab === 'spreads') this.loadSpreads(1);
        },

        async loadTopItems() {
          if (this.analysisTopItems.length) return;
          try {
            const r = await fetch('/api/analysis/rankings?sort_by=sell_score&sort_order=desc&page_size=6');
            if (r.ok) { const d = await r.json(); this.analysisTopItems = d.items || []; }
          } catch (e) { this.showToast(e.message || '加载排行数据失败', 'error'); }
        },

        async openScoreBucket(i) {
          const ranges = [[0,30],[30,50],[50,70],[70,85],[85,100]];
          const labels = [this.t('score_hold'),this.t('score_neutral'),this.t('score_consider'),this.t('score_strong'),this.t('score_urgent')];
          const [min, max] = ranges[i];
          this.scoreBucket = { show: true, label: labels[i], min, max, items: [] };
          try {
            const r = await fetch(`/api/analysis/rankings?sort_by=sell_score&sort_order=desc&min_score=${min}&max_score=${max}&page_size=50`);
            if (r.ok) { const d = await r.json(); this.scoreBucket.items = d.items || []; }
          } catch (e) { this.showToast(e.message || '加载评分区间失败', 'error'); }
        },

        async loadAlerts(page) {
          this.alertPage = page || 1;
          const p = new URLSearchParams({ page: this.alertPage, page_size: 20 });
          if (this.alertFilter.severity) p.set('severity', this.alertFilter.severity);
          if (this.alertFilter.type) p.set('alert_type', this.alertFilter.type);
          if (this.alertFilter.unreadOnly) p.set('unread_only', 'true');
          try {
            const r = await fetch('/api/analysis/alerts?' + p);
            if (r.ok) this.analysisAlerts = await r.json();
          } catch (e) { this.showToast(e.message || '加载预警列表失败', 'error'); }
        },

        async markAlertRead(a) {
          await fetch(`/api/analysis/alerts/${a.id}/read`, { method: 'PATCH' });
          a.is_read = true;
          this.unreadAlertCount = Math.max(0, this.unreadAlertCount - 1);
        },

        async markAllAlertsRead() {
          await fetch('/api/analysis/alerts/read-all', { method: 'POST' });
          this.analysisAlerts.items.forEach(a => a.is_read = true);
          this.unreadAlertCount = 0;
        },

        async loadSpreads(page) {
          const p = new URLSearchParams({ page, page_size: 30, min_spread: this.minSpread });
          try {
            const r = await fetch('/api/analysis/spreads?' + p);
            if (r.ok) this.analysisSpreads = await r.json();
          } catch (e) { this.showToast(e.message || '加载价差数据失败', 'error'); }
        },

        async searchAnalysisItems() {
          const q = this.analysisSearch.trim();
          try {
            const r = await fetch('/api/analysis/search-items?q=' + encodeURIComponent(q) + '&limit=15');
            if (r.ok) { const d = await r.json(); this.analysisSearchResults = d.items || []; }
          } catch (e) { this.showToast(e.message || '搜索物品失败', 'error'); }
        },

        async loadItemSignals(name) {
          this.itemSignals = null;
          try {
            const r = await fetch(`/api/analysis/signals?market_hash_name=${encodeURIComponent(name)}&days=${this.chartDays}`);
            if (r.ok) {
              this.itemSignals = await r.json();
              this.$nextTick(() => this.renderPriceChart());
            }
          } catch (e) { this.showToast(e.message || '加载信号数据失败', 'error'); }
        },

        renderPriceChart() {
          if (this._priceChart) { this._priceChart.destroy(); this._priceChart = null; }
          const el = document.getElementById('priceChart');
          if (!el || !this.itemSignals?.chart_data?.length) return;

          const raw = this.itemSignals.chart_data;
          const isDark = !document.documentElement.classList.contains('light');
          const textColor = isDark ? '#64748b' : '#475569';
          const gridColor = isDark ? 'rgba(51,65,85,0.2)' : 'rgba(186,214,235,0.3)';

          // 时间范围过滤
          let data = raw;
          if (this.chartDays > 0) {
            const cutoff = Date.now() - this.chartDays * 86400e3;
            data = raw.filter(d => { const s=d.date; return new Date(s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)).getTime() >= cutoff; });
          }
          const cats = data.map(d => { const s=d.date; return s.slice(4,6)+'/'+s.slice(6,8); });
          const mkS = (name, key, color, w, dash) => ({ name, data: data.map(d => d[key] ?? null), color, strokeWidth: w, dashArray: dash || 0 });

          this._priceChart = new ApexCharts(el, {
            chart: { type: 'line', height: 280, background: 'transparent', toolbar: { show: false }, zoom: { enabled: true }, fontFamily: 'ui-monospace, monospace' },
            series: [
              { name: this.nameLang==='cn'?'收盘价':'Close', data: data.map(d=>d.close) },
              { name: 'MA7', data: data.map(d=>d.ma7) },
              { name: 'MA30', data: data.map(d=>d.ma30) },
              { name: 'BB Upper', data: data.map(d=>d.bb_upper) },
              { name: 'BB Lower', data: data.map(d=>d.bb_lower) },
            ],
            stroke: { curve: 'straight', width: [2, 1, 1, 1, 1], dashArray: [0, 4, 6, 3, 3] },
            colors: ['#3b82f6', '#f59e0b', '#8b5cf6', 'rgba(100,116,139,0.4)', 'rgba(100,116,139,0.4)'],
            fill: { opacity: [1, 0, 0, 0, 0] },
            dataLabels: { enabled: false },
            xaxis: { categories: cats, labels: { style: { colors: textColor, fontSize: '9px' }, rotate: 0, hideOverlappingLabels: true }, tickAmount: 10, axisBorder: { show: false }, axisTicks: { show: false } },
            yaxis: { labels: { style: { colors: textColor, fontSize: '10px' }, formatter: v => v != null ? '¥'+Number(v).toLocaleString() : '' } },
            grid: { borderColor: gridColor, strokeDashArray: 3 },
            legend: { labels: { colors: '#94a3b8' }, fontSize: '10px', markers: { width: 10, height: 10 } },
            tooltip: { theme: isDark ? 'dark' : 'light', shared: true, intersect: false },
            theme: { mode: isDark ? 'dark' : 'light' },
          });
          this._priceChart.render();
        },

        async triggerBackfill() {
          this.backfillRunning = true;
          this.backfillProgress = '启动中…';
          try {
            await fetch('/api/analysis/backfill', { method: 'POST' });
            const poll = setInterval(async () => {
              try {
                const r = await fetch('/api/analysis/collector/status');
                if (r.ok) {
                  const d = await r.json();
                  const bf = d.backfill;
                  this.backfillProgress = `${bf.done}/${bf.total} ${bf.progress||''}`;
                  if (bf.status !== 'running') {
                    clearInterval(poll);
                    this.backfillRunning = false;
                    this.showToast(bf.status === 'done' ? '历史数据回填完成' : '回填异常: ' + bf.progress, bf.status === 'done' ? 'success' : 'error');
                    this.loadAnalysis();
                  }
                }
              } catch (e) { console.warn('Backfill poll error:', e.message); }
            }, 3000);
          } catch (e) {
            this.backfillRunning = false;
            this.showToast('回填启动失败', 'error');
          }
        },

        async triggerComputeNow() {
          this.computingSignals = true;
          try {
            const r = await fetch('/api/analysis/compute-now', { method: 'POST' });
            if (r.ok) {
              const d = await r.json();
              this.showToast(d.message || '信号计算完成', 'success');
              this.loadAnalysis();
            } else {
              this.showToast('计算失败', 'error');
            }
          } catch (e) { this.showToast('计算失败: ' + e.message, 'error'); }
          finally { this.computingSignals = false; }
        },

        async collectNow() {
          try {
            this.showToast('价格采集已触发，后台运行中（约8分钟）', 'success');
          } catch (e) { this.showToast(e.message || '价格采集触发失败', 'error'); }
        },

        async triggerCsqaqSync() {
          try {
            const r = await fetch('/api/analysis/csqaq-sync?mode=sync', { method: 'POST' });
            const d = await r.json();
            if (d.started) {
              this.showToast(d.message || 'CSQAQ 同步已启动', 'success');
              // Poll status
              const poll = setInterval(async () => {
                try {
                  const sr = await fetch('/api/analysis/csqaq-status');
                  const st = await sr.json();
                  if (st.status === 'idle' && (st.synced > 0 || st.mapped > 0)) {
                    clearInterval(poll);
                    this.showToast(`CSQAQ 同步完成: ${st.mapped||0} 映射, ${st.synced||0} 同步`, 'success');
                    this.loadAnalysis();
                  }
                } catch (e) { console.warn('CSQAQ sync poll error:', e.message); }
              }, 5000);
              // Auto-stop polling after 15 min
              setTimeout(() => clearInterval(poll), 900000);
            } else {
              this.showToast(d.message || 'CSQAQ 同步繁忙', 'warning');
            }
          } catch (e) { this.showToast('CSQAQ 同步失败: ' + e.message, 'error'); }
        },

        toggleTheme() {
          this.theme = this.theme === 'dark' ? 'light' : 'dark';
          localStorage.setItem('theme', this.theme);
          document.documentElement.classList.toggle('light', this.theme === 'light');
        },

        scoreColor(s) {
          if (s == null) return 'text-slate-400';
          if (s >= 85) return 'text-red-400';
          if (s >= 70) return 'text-orange-400';
          if (s >= 50) return 'text-yellow-400';
          if (s >= 30) return 'text-slate-400';
          return 'text-emerald-400';
        },
        scoreLabel(s) {
          if (s == null) return '';
          if (s >= 85) return this.t('label_urgent');
          if (s >= 70) return this.t('label_strong');
          if (s >= 50) return this.t('label_consider');
          if (s >= 30) return this.t('label_neutral');
          return this.t('label_hold');
        },
        catLabel(c) {
          const key = 'cat_' + c;
          return this.t(key) !== key ? this.t(key) : c;
        },

        // ── Rental yield calculation ─────────────────────────────────
        // 优先使用 CSQAQ 市场租金年化数据，fallback 到货架数据估算
        rentalYield(signals) {
          // 1. 优先使用 CSQAQ 信号数据（市场租金年化）
          if (signals?.signal?.rental_annual > 0) {
            return signals.signal.rental_annual;
          }
          if (!signals?.ownership) return 0;
          const price = signals.ownership.current_price;
          if (!price || price <= 0) return 0;
          // 2. Fallback: 从货架数据估算
          const allShelf = [...(this.leaseShelf.items||[]), ...(this.subletList.items||[])];
          const match = allShelf.find(i => (i.commodityHashName||i.marketHashName||'') === signals.market_hash_name);
          if (match) {
            const dailyRent = match.leaseUnitPrice || match.LeaseUnitPrice || 0;
            if (dailyRent > 0) {
              const effectiveDays = this.youpinMembership ? 310 : 188;
              return Math.round(effectiveDays * dailyRent / price * 100 * 10) / 10;
            }
          }
          return 0;
        },

        // ── 含租预期年收益率 ──────────────────────────────────────────
        // 假设饰品价格不变，收一年租金后的总回报率
        projectedReturn(signals) {
          const s = signals?.signal;
          const o = signals?.ownership;
          if (!s || !o?.purchase_price || o.purchase_price <= 0) return null;
          const currentPrice = o.current_price || 0;
          if (currentPrice <= 0) return null;
          const dailyRent = s.daily_rent || 0;
          if (dailyRent <= 0) {
            // 无租金数据时退化为纯盈亏率
            return s.pnl_rate != null ? s.pnl_rate : null;
          }
          const effectiveDays = this.youpinMembership ? 310 : 188;
          const annualRent = dailyRent * effectiveDays;
          return Math.round((currentPrice + annualRent - o.purchase_price) / o.purchase_price * 1000) / 10;
        },

        // ── Helpers ───────────────────────────────────────────────────

        // 货架图片 URL（优先用 imgUrl，fallback icon_url）
        shelfImgUrl(item) {
          const raw = item.imgUrl || item.imgurl || item.icon_url || item.IconUrl;
          if (!raw) return '';
          // 悠悠自有 CDN 地址（非 steam 路径）直接返回
          if (raw.startsWith('http')) return raw;
          // Steam economy icon 路径
          return `https://community.fastly.steamstatic.com/economy/image/${raw}/62fx62f`;
        },

        // CS2 品质色 — 精确匹配游戏内 rarity 颜色
        // Consumer=#b0c3d9, Industrial=#5e98d9, Mil-Spec=#4b69ff, Restricted=#8847ff,
        // Classified=#d32ce6, Covert=#eb4b4b, Contraband=#e4ae39, ★金色=#ffd700
        _rarityStyles: {
          contraband:  'color:#e4ae39',    // 禁忌 (Howl等) — 金橙
          covert:      'color:#eb4b4b',    // 隐秘 — 红
          classified:  'color:#d32ce6',    // 保密 — 粉紫
          restricted:  'color:#8847ff',    // 受限 — 紫
          milspec:     'color:#4b69ff',    // 军规 — 蓝
          industrial:  'color:#5e98d9',    // 工业 — 天蓝
          consumer:    'color:#b0c3d9',    // 消费 — 浅灰蓝
          gold:        'color:#ffd700',    // ★ 金色
          stattrak:    'color:#cf6a32',    // StatTrak™ 橙
          souvenir:    'color:#ffD700',    // 纪念品 金
          highgrade:   'color:#b0c3d9',    // High Grade
          base:        'color:#b0c3d9',    // 默认
        },

        rarityClass(hashName, itemType) {
          // 从 item_type 精确判断 (如 "Covert Rifle", "Classified Pistol")
          if (itemType) {
            const t = itemType.toLowerCase();
            if (t.includes('contraband')) return '';
            if (t.includes('extraordinary') || t.includes('covert')) {
              return '';
            }
            if (t.includes('classified')) return '';
            if (t.includes('restricted')) return '';
            if (t.includes('mil-spec') || t.includes('mil_spec')) return '';
            if (t.includes('industrial')) return '';
            if (t.includes('consumer') || t.includes('base grade')) return '';
            if (t.includes('high grade')) return '';
          }
          return '';
        },

        // Returns inline style for rarity color
        rarityStyle(hashName, itemType) {
          const S = this._rarityStyles;
          // 1. Use item_type if available (precise from Steam API)
          if (itemType) {
            const t = itemType.toLowerCase();
            if (t.includes('contraband')) return S.contraband;
            if (t.includes('extraordinary') || t.includes('covert')) {
              if (hashName && hashName.startsWith('★')) return S.gold;
              return S.covert;
            }
            if (t.includes('classified')) return S.classified;
            if (t.includes('restricted')) return S.restricted;
            if (t.includes('mil-spec') || t.includes('mil_spec')) return S.milspec;
            if (t.includes('industrial')) return S.industrial;
            if (t.includes('consumer') || t.includes('base grade')) return S.consumer;
            if (t.includes('high grade')) return S.highgrade;
          }
          // 2. Fallback: pattern match on name
          if (!hashName) return S.base;
          // ★ items (knives/gloves) → Gold
          if (hashName.startsWith('★')) return S.gold;
          // Contraband
          if (hashName.includes('M4A4 | Howl')) return S.contraband;
          // StatTrak™ — show orange accent
          if (hashName.startsWith('StatTrak™')) return S.stattrak;
          // Souvenir
          if (hashName.startsWith('Souvenir')) return S.souvenir;
          // Covert weapons (known covert skins by weapon prefix heuristic)
          const covertSkins = ['AWP | Dragon Lore','AWP | Gungnir','AK-47 | Wild Lotus','AK-47 | Gold Arabesque',
            'Desert Eagle | Ocean Drive','M4A4 | Temukau','AK-47 | Inheritance','M4A1-S | Welcome to the Jungle'];
          if (covertSkins.some(s => hashName.includes(s))) return S.covert;
          // Stickers, Cases, Keys — typically consumer/industrial
          if (hashName.startsWith('Sticker |') || hashName.startsWith('Patch |')) return S.highgrade;
          if (hashName.includes(' Case') || hashName.includes('Capsule')) return S.milspec;
          if (hashName.startsWith('Sealed Graffiti')) return S.industrial;
          if (hashName.startsWith('Charm |')) return S.restricted;
          if (hashName.startsWith('Music Kit |') || hashName.startsWith('StatTrak™ Music Kit')) return S.highgrade;
          // Default: base grade
          return S.base;
        },

        // Convert JS Date → "MM-DD HH:mm" or "MM-DD" in US Pacific time
        _toPT(d, time = true) {
          const s = d.toLocaleString('sv-SE', { timeZone: 'America/Los_Angeles' });
          return time ? s.slice(5, 16) : s.slice(5, 10);
        },
        // Format "YYYYMMDDHHmm" (UTC) → "MM-DD HH:mm" (PT)
        fmtMinute(s) {
          if (!s || s.length < 12) return '—';
          const d = new Date(Date.UTC(+s.slice(0,4), +s.slice(4,6)-1, +s.slice(6,8), +s.slice(8,10), +s.slice(10,12)));
          return this._toPT(d);
        },
        // Format "YYYYMMDD" (UTC) → "MM-DD" (PT)
        fmtDate(s) {
          if (!s || s.length < 8) return '—';
          const d = new Date(Date.UTC(+s.slice(0,4), +s.slice(4,6)-1, +s.slice(6,8), 12, 0));
          return this._toPT(d, false);
        },
        // Format "YYYY-MM-DD HH:mm" (UTC) → "MM-DD HH:mm" (PT)
        fmtUtcStr(s) {
          if (!s) return '—';
          const d = new Date(s.replace(' ', 'T') + (s.includes('Z') || s.includes('+') ? '' : 'Z'));
          return isNaN(d) ? s : this._toPT(d);
        },
        fmt(n) {
          if (n == null) return '—';
          return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
        },
        pct(part, total) {
          if (!total || part == null) return 0;
          return Math.round(part / total * 100);
        },
        iconUrl(url, size = 62) {
          if (!url) return '';
          if (url.startsWith('http')) return url;
          return `https://community.fastly.steamstatic.com/economy/image/${url}/${size}fx${size}f`;
        },
        statusLbl(s) {
          const map = {
            in_steam: this.t('status_steam'),
            rented_out: this.t('status_rented'),
            in_storage: this.t('status_storage'),
            sold: this.t('status_sold'),
          };
          return map[s] || s || '—';
        },
        statusCls(s) {
          return {
            in_steam:   'bg-blue-500/10 text-blue-400',
            rented_out: 'bg-green-500/10 text-green-400',
            in_storage: 'bg-purple-500/10 text-purple-400',
            sold:       'bg-slate-800 text-slate-600',
          }[s] || 'bg-slate-800 text-slate-600';
        },
        importLbl(k) {
          if (this.nameLang === 'en') return { stock:'Stock (STEAM)', lease:'Lease (rented)', buy:'Buy Records', sell:'Sell Records' }[k] || k;
          return { stock:'库存 (STEAM_PROTECTED)', lease:'租赁 (rented_out)', buy:'购买记录匹配', sell:'出售记录标记' }[k] || k;
        },
        importFields(data) {
          const lm = this.nameLang === 'cn' ? {
            total_fetched:'拉取条数', upserted:'写入/更新', skipped:'跳过',
            total_records:'拉取条数', updated:'匹配更新', not_found_in_db:'未在库存',
            stats:'租赁统计', valuation:'悠悠估值',
          } : {
            total_fetched:'Fetched', upserted:'Upserted', skipped:'Skipped',
            total_records:'Records', updated:'Matched', not_found_in_db:'Not in DB',
            stats:'Lease Stats', valuation:'Valuation',
          };
          return Object.entries(data)
            .filter(([k]) => !['items','not_found_names'].includes(k))
            .map(([k,v]) => [lm[k]||k, v]);
        },
        showToast(msg, type = 'success') {
          this.toast = { msg, type };
          setTimeout(() => { this.toast = { msg:'', type:'success' }; }, 3000);
        },
      };
    }
