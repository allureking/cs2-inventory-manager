    // ── AURORA 指针追光：卡片表面跟随光标的环境光斑（写入 CSS 变量,纯视觉）──
    // 单个委托监听 + rAF 节流。
    (() => {
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      // v0.13.3：真正做到"触屏零开销"。此前只挡了 reduced-motion,而 pointermove
      // 在触摸滚动时同样触发,每帧 closest() + getBoundingClientRect()(强制同步布局)
      // 只为驱动 .card:hover::after —— 触摸设备永远看不到该效果,纯属滚动掉帧。
      if (!matchMedia('(hover: hover) and (pointer: fine)').matches) return;
      let raf = 0;
      document.addEventListener('pointermove', (e) => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          raf = 0;
          const card = e.target.closest?.('.card, .glass-chart, .glass-solid');
          if (!card) return;
          const r = card.getBoundingClientRect();
          card.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(2) + '%');
          card.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(2) + '%');
        });
      }, { passive: true });
    })();

    // ── 会话守卫（v0.10.0 用户系统）：任何 /api/ 请求收到 401 即视为未登录/会话过期，
    // 跳转登录页（/api/auth/* 除外，由登录页自身处理错误提示）。
    // 0.9.x 的 X-API-Key 弹窗注入已废弃：浏览器走 session cookie，API key 仅留给脚本/curl。
    (() => {
      const orig = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const resp = await orig(input, init);
        if (resp.status === 401 && url.startsWith('/api/') && !url.startsWith('/api/auth/')) {
          window.location.href = '/login';
        }
        return resp;
      };
    })();

    const _CHANGELOG = Object.freeze([
          {
            version: '0.13.0', date: '2026-06-11', major: true,
            title_cn: '可靠性与数据资产大修：凭证哨兵 + 租赁实绩 + 成本找回',
            title_en: 'Reliability & Data Overhaul: Credential Sentinel + Lease Attribution + Cost Recovery',
            added: [
              ['凭证哨兵：每日自动探测悠悠 Token,失效立即在预警中心告警(支持 Server酱/Telegram 推送,.env 配置即生效),恢复后自动愈合——数据停更不再静默', 'Credential sentinel: daily YouPin token probe with in-app critical alert (optional ServerChan/Telegram push), auto-heals on recovery'],
              ['单品租赁实绩归因：每日记录每件饰品的实际出租与日租金,单品分析页新增「租赁实绩」卡(有租天数/实收租金/实际年化)+ 实绩排行 API——回答「该卖谁、该续谁」', 'Per-item lease income attribution: daily per-commodity rent recording, new "Actual Lease Income" card + rankings API'],
              ['GitHub Actions CI：每次 push/PR 云端跑全量回归(360+ 用例),与本地 pre-commit 双闸', 'GitHub Actions CI running the full regression suite on every push/PR'],
            ],
            fixed: [
              ['成本找回：532 件活跃持仓从僵尸行继承回 ¥652,704 购入成本(磨损值精确指纹,零歧义才迁移);PnL 覆盖 +532 件', 'Cost recovery: 532 active items inherited ¥652,704 purchase costs from zombie rows via exact-wear fingerprint matching'],
              ['僵尸行源头根治：租赁导入改为按磨损指纹复用旧行(此前每个租赁周期都新建行,成本断链、每月净增 ~15k 死行)', 'Zombie-row root fix: lease import now reuses rows by wear fingerprint instead of creating new ones every cycle'],
              ['监控修真：/status 不再永远 degraded(新鲜度阈值改 26h),调度任务列表改为实时读取', 'Monitoring fixed: /status no longer permanently degraded (26h threshold), live scheduler job list'],
            ],
            changed: [
              ['数据库瘦身:VACUUM 489→77MB;备份改 VACUUM INTO+gzip(单份 468→25MB),并完成首次恢复演练;归档清理 24.4 万死行(item 字典/停用平台历史/旧告警/快照降采样,先归档后删)', 'DB slimmed 489→77MB; backups now VACUUM INTO+gzip (468→25MB) with restore drill done; 244k dead rows archived & pruned'],
              ['SteamDT 采价 4005 限速自动等窗重试;新增多个查询索引', 'SteamDT 4005 rate-limit retry; new query indexes'],
            ],
            commits: [],
          },
          {
            version: '0.12.0', date: '2026-06-10', major: true,
            title_cn: '性能提速：刷新不再卡顿 + 数据自动保鲜',
            title_en: 'Performance: No More Slow Refreshes + Auto-Fresh Data',
            added: [
              ['首屏骨架屏：数据到达前显示流光占位，告别空白闪烁', 'Loading skeletons: shimmer placeholders before data arrives, no more blank flash'],
              ['数据自动保鲜：页面停留每 5 分钟静默刷新；切回标签页若数据过期立即更新，无需手动刷新', 'Auto-fresh data: silent refresh every 5 min while visible; instant update when returning to a stale tab'],
            ],
            fixed: [
              ['「偶尔刷新很慢」根因修复：概览估值缓存过期时不再阻塞等待悠悠 API 1-3 秒，改为先返回现值、后台静默更新（stale-while-revalidate）', '"Occasionally slow refresh" root-caused: overview no longer blocks 1-3s on YouPin API at cache expiry — serves current value and revalidates in background'],
              ['库存估值解析修复：dashboard 处理带 ¥ 符号的估值时不再静默失败（v0.9.3 漏网处）', 'Inventory valuation parse fix: dashboard no longer silently fails on ¥-prefixed values (spot missed in v0.9.3)'],
              ['市价采集限速韧性：命中 SteamDT 4005 限速自动等窗重试，连续两晚价格停更的问题不再发生', 'Price collection resilience: auto-retry after SteamDT 4005 rate limit; fixes 2-night price staleness'],
              ['量化分析搜索/排行在 SQLite 下的重复行隐患（DISTINCT ON 静默忽略）', 'Analysis search/rankings dedup correctness on SQLite (DISTINCT ON silently ignored)'],
            ],
            changed: [
              ['量化总览/图表聚合加 5 分钟缓存（原每次 0.2-0.6 秒全表扫描），手动计算/标记已读后立即失效', 'Analysis overview / chart aggregations now cached 5 min (was 0.2-0.6s full scans); invalidated on compute / mark-read'],
              ['全站盈亏口径统一：旧库存接口逐件盈亏从「仅 BUFF 价」改为「可得平台最低价」，与仪表盘一致', 'Sitewide P&L unification: legacy inventory per-item P&L now uses cheapest available platform price, matching dashboard'],
              ['quant_signal/price_history 新增查询索引', 'New query indexes on quant_signal / price_history'],
            ],
            commits: [],
          },
          {
            version: '0.11.0', date: '2026-06-10', major: true,
            title_cn: 'AURORA 设计系统：全站 UI 升级',
            title_en: 'AURORA Design System: Sitewide UI Upgrade',
            added: [
              ['动态极光背景 + 胶片颗粒质感，oklch 广色域配色，暗色「深空极光」/ 亮色「晨雾蓝瓷」双主题', 'Living aurora background with film grain, oklch wide-gamut palette, dual themes (deep-space / morning-mist)'],
              ['液态玻璃表面：卡片镜面上缘高光、指针追光（光标处环境光斑）、悬浮浮起与极光描边', 'Liquid-glass surfaces: specular top edge, cursor-following ambient light, hover lift with aurora ring'],
              ['主题切换圆形揭幕动画（View Transitions API），统计卡彩色顶缘光带 + 金融级等宽数字', 'Circular-reveal theme switching (View Transitions API), color-coded stat card accents, tabular-nums financial digits'],
              ['弹簧物理动效（CSS linear() 缓动）贯穿按钮/模态框/Tab 切换；prefers-reduced-motion 全量降级', 'Spring-physics motion (CSS linear() easing) across buttons/modals/tabs; full prefers-reduced-motion fallback'],
            ],
            changed: [
              ['登录页同步 AURORA 设计语言；所有视觉为纯叠加层，零业务逻辑改动', 'Login page restyled to match; pure overlay layer, zero business-logic changes'],
            ],
            commits: [],
          },
          {
            version: '0.10.0', date: '2026-06-10', major: true,
            title_cn: '用户系统：账号登录 + 密码管理',
            title_en: 'User System: Account Login + Password Management',
            added: [
              ['应用级账号登录（superadmin 超级管理员），HttpOnly session cookie，30 天有效；登录页 /login', 'App-level account login (superadmin) with HttpOnly session cookie (30-day); login page at /login'],
              ['右上角账户区：显示当前用户、修改密码（旧 session 自动失效）、退出登录', 'Header account area: current user, change password (invalidates old sessions), logout'],
              ['登录限速：同 IP+用户名 5 次失败锁 5 分钟；忘记密码可 SSH 运行 scripts/create_user.py --reset 重置', 'Login throttle: 5 failures / 5 min lockout; forgot password → reset via scripts/create_user.py --reset over SSH'],
            ],
            changed: [
              ['取代 nginx Basic Auth 双重弹窗；X-API-Key 仅保留给脚本/curl，浏览器写操作走登录会话，不再弹 API Key 输入框', 'Replaces the nginx Basic Auth double prompt; X-API-Key kept for scripts/curl only — browser writes use the login session, no more key prompt'],
            ],
            commits: [],
          },
          {
            version: '0.9.3', date: '2026-06-10', major: false,
            title_cn: '数据质量：估值解析修复 + 历史数据防污染',
            title_en: 'Data Quality: Valuation Parse Fix + History Anti-Pollution',
            fixed: [
              ['修复悠悠估值带 ¥ 前缀时解析崩溃导致每日追踪静默混用两套估值口径；fallback 发生时在备注写入 valuation_source=snapshot 标记', "Fixed valuation parse crash on '¥'-prefixed strings that silently mixed two valuation methodologies in daily tracker; fallback now writes a valuation_source=snapshot marker to notes"],
              ['历史回填的合成数据不再覆盖真实日线，只允许填补完全没有记录的日期；新增脚本恢复被覆盖的 45 天 ALL 聚合行', 'Backfill synthetic data can no longer overwrite real daily rows (fills empty dates only); new script restores the 45 days of overwritten ALL aggregate rows'],
              ['0 价占位行（停用平台/抓取失败）不再拖垮跨平台 ALL 聚合——历史上 ~20% 的 ALL 日线因此为 0', 'Zero-price placeholder rows (disused platforms / failed fetches) no longer drag the cross-platform ALL aggregate to 0 (~20% of ALL rows historically)'],
            ],
            commits: [],
          },
          {
            version: '0.9.2', date: '2026-06-10', major: false,
            title_cn: '安全加固：写操作 API Key 鉴权',
            title_en: 'Security Hardening: API-Key Auth for Write Operations',
            added: [
              ['服务端 APP_API_KEY 启用后，所有 /api/ 写请求（改价/上架/下架/导入等）须携带密钥；新增 X-API-Key 头支持以兼容 nginx Basic Auth', 'With APP_API_KEY set, all /api/ write requests (reprice/list/delist/import) require the key; new X-API-Key header support coexists with nginx Basic Auth'],
              ['前端自动附带密钥：首次写操作弹窗输入一次，存 localStorage 后续自动注入', 'Frontend auto-attaches the key: prompted once on first write, stored in localStorage and injected automatically'],
            ],
            commits: [],
          },
          {
            version: '0.9.1', date: '2026-06-08', major: false,
            title_cn: '图表渲染修复（桌面 resize 崩溃 + iOS 空白）',
            title_en: 'Chart Rendering Fixes (desktop resize crash + iOS blank)',
            fixed: [
              ['桌面端图表 resize 崩溃：窗口缩放/开 DevTools 时图表变空白且无法恢复——移除 fingerprint 中的宽度,避免与 Chart.js 原生 responsive 双重重建导致 getContext 报错', 'Desktop chart resize crash: charts blanked on window resize / DevTools — removed width from fingerprint to stop double-rebuild racing Chart.js responsive (getContext null)'],
              ['iOS WebKit 概览图表空白:iOS 丢弃视口外 canvas 后备存储,导致折叠下方的持仓构成/盈亏排名/盈亏率分布绘制后空白——滚入视口时强制重绘修复(桌面/DevTools 无此问题)', 'iOS WebKit blank overview charts: iOS drops off-screen canvas backing store — force re-render on scroll-into-view (not reproducible on desktop/DevTools)'],
            ],
            commits: [],
          },
          {
            version: '0.9.0', date: '2026-06-08', major: true,
            title_cn: '数据可视化升级 + 全面移动端适配',
            title_en: 'Data-Viz Upgrade + Full Mobile Optimization',
            added: [
              ['概览新增持仓构成环形图、盈亏 Top 涨跌排行、盈亏率分布、持仓价值 Top20 图标网格', 'Overview: type-composition doughnut, P&L gainers/losers ranking, P&L-rate distribution, Top-20 holdings icon grid'],
              ['新增只读聚合接口 /api/dashboard/chart-data 为新图表供数', 'New read-only /api/dashboard/chart-data aggregation endpoint feeding the charts'],
              ['移动端顶栏「更多」抽屉 + 横向滚动 Tab 栏，主操作（同步）常驻', 'Mobile header "More" drawer + horizontal-scroll tab bar, primary Sync action always visible'],
              ['移动端持仓列表卡片化（点击复用详情侧栏），收益追踪表 sticky 左固定首列', 'Mobile holdings list card-ified (taps reuse detail panel), tracker table sticky left column'],
            ],
            fixed: [
              ['图表渲染根因修复：0 宽渲染不再被缓存成永久空白；切换隐藏 Tab 再切回不再空白', 'Chart lifecycle fix: width-0 renders never cached blank; switching to a hidden tab and back no longer blanks'],
              ['图表 resize 崩溃修复：移除指纹中的宽度，避免与 Chart.js 原生 responsive 双重重建导致 getContext 报错/空白', 'Resize-crash fix: removed width from fingerprint to stop double-rebuild racing Chart.js responsive (getContext null / blank)'],
              ['消除移动端页面级横向溢出（顶栏/侧栏/宽表父链）', 'Eliminated page-level horizontal overflow on mobile (header / side panel / wide-table parents)'],
            ],
            changed: [
              ['概览 6 张统计卡精简为 4 张信息密度更高的玻璃卡（大数字显示完整精确值，hover 看精确）', 'Overview stat cards consolidated 6→4 denser glass cards (full precise big numbers, hover for exact)'],
              ['图表跟随三态主题（light/dark/system），ApexCharts 收益/价格图主题色不再写死', 'Charts follow light/dark/system theme; ApexCharts tracker/price colors no longer hardcoded'],
              ['移动端字号≥12px、主操作点击高度≥40px、隐藏次要时间戳、模态可滚动、表格整页滚动', 'Mobile: body ≥12px, primary tap targets ≥40px, secondary timestamps hidden, scrollable modals, page-scroll tables'],
            ],
            commits: [],
          },
          {
            version: '0.8.0', date: '2026-06-08', major: true,
            title_cn: '成本管理与利润监控 — Phase 2/3',
            title_en: 'Cost Management & Profit Monitoring — Phase 2/3',
            added: [
              ['悠悠有品交易记录导入工具：5 级智能匹配（commodity_id → asset_id → hash+磨损 → hash_name → 中文名），FIFO 多实例绑定', 'YouPin trade record import tool: 5-level smart matching (commodity_id → asset_id → hash+wear → hash_name → cn_name), FIFO multi-instance binding'],
              ['手动成本录入 CLI：list/set/set-id/batch/stats 命令，Rich 表格展示', 'Manual cost entry CLI: list/set/set-id/batch/stats commands with Rich tables'],
              ['利润监控终端仪表盘：持仓总览、PnL 排行、信号高亮、--watch 持续刷新', 'Profit monitoring CLI dashboard: portfolio overview, PnL ranking, signal highlights, --watch mode'],
              ['YAML 告警规则外置：7 条全局规则 + 按类目（刀/手套/贴纸）阈值覆盖，热加载', 'YAML alert rules: 7 global rules + per-category threshold overrides (knife/glove/sticker), hot reload'],
              ['库存/租赁同步诊断日志：每次同步后对比 API 聚合值 vs 实际遍历值', 'Sync diagnostic logging: compare API aggregate vs actual traversal after each sync'],
            ],
            fixed: [
              ['租赁分页不再依赖 API 的 totalCount（可能缓存偏小），改为循环到空页为止', 'Lease pagination no longer relies on API totalCount (may be stale), loops until empty page'],
            ],
            changed: [
              ['Phase 1 降频优化：采价间隔从 30min 调至 2h，快照从 15min 调至 1h，缓存 TTL 扩展至 30min', 'Phase 1 tuning: price collection 30min→2h, snapshots 15min→1h, cache TTL extended to 30min'],
              ['新增 rich、pyyaml 依赖', 'Added rich, pyyaml dependencies'],
            ],
            commits: [
              { hash: 'dfb047c', msg: 'fix: 租赁分页不再依赖 totalCount，改为循环到空页', date: '06-08' },
              { hash: 'f7ff1ce', msg: 'feat: 成本管理与利润监控工具链 (Phase 2/3)', date: '06-08' },
              { hash: '5f964f4', msg: 'diag: 添加任务链观测日志', date: '06-05' },
              { hash: '8e43113', msg: 'perf: 阶段一精简 — 降频采价/快照 + 扩展缓存', date: '06-05' },
            ],
          },
          {
            version: '0.7.0', date: '2026-05-29', major: true,
            title_cn: 'UI 重构 & 性能优化 & 新功能',
            title_en: 'UI Overhaul, Performance & New Features',
            added: [
              ['挂售快照功能：保存货架数据供下架后参考', 'Listing snapshot: save shelf data for reference after delisting'],
              ['加仓/减仓快捷操作：收益追踪成本基准调整', 'Position sizing shortcuts: adjust cost basis for income tracking'],
              ['概览走势图双大类切换（组合价值 + 租赁走势）', 'Overview chart dual-category toggle (portfolio value + rental trends)'],
              ['月度汇总缺失天数预估 + 日报表全列可编辑', 'Monthly summary missing-day estimation + editable daily report columns'],
            ],
            fixed: [
              ['多 worker 环境下 token 同步：修复导入 84101 错误', 'Multi-worker token sync: fixed import 84101 error'],
              ['Chart.js resize 无限递归导致图表消失', 'Chart.js resize infinite recursion causing charts to vanish'],
              ['快照保存处理空字符串字段转换', 'Snapshot save handles empty string field conversion'],
              ['库存市值计算统一为悠悠 API 估值', 'Unified market value calculation to use YouPin API valuation'],
            ],
            changed: [
              ['首页改为资产概览+持仓列表合并，收益追踪移至第二 Tab', 'Homepage merged into overview + holdings, income tracker moved to 2nd tab'],
              ['概览走势图从 ApexCharts 迁回 Chart.js 4.4.0（稳定性）', 'Overview charts migrated back from ApexCharts to Chart.js 4.4.0 (stability)'],
              ['全面性能优化：持久 HTTP 客户端、N+1 查询修复、JS 代码分割、Pydantic 请求模型', 'Performance: persistent HTTP client, N+1 query fixes, JS code splitting, Pydantic request models'],
              ['Tracker 表格默认只渲染 30 行，减少 Alpine 绑定数 5600→1200', 'Tracker table renders 30 rows by default, reducing Alpine bindings 5600→1200'],
              ['定时任务改为 PDT 时区', 'Scheduled tasks switched to PDT timezone'],
            ],
            commits: [
              { hash: '73379aa', msg: 'fix: 多 worker 环境下 token 同步', date: '05-29' },
              { hash: '3397784', msg: 'perf: 持久HTTP客户端 + N+1修复 + JS代码分割', date: '05-24' },
              { hash: 'd3220f7', msg: 'perf: 全面性能优化 + 安全加固', date: '05-24' },
              { hash: '50fa646', msg: 'feat: 加仓/减仓 - 收益追踪成本基准快捷调整', date: '05-24' },
              { hash: '70fc3a3', msg: 'feat: 挂售快照功能', date: '05-22' },
              { hash: '7a0700d', msg: 'refactor: 概览走势图改用 Chart.js 4.4.0', date: '04-08' },
              { hash: '0b50ad4', msg: 'feat: 首页改为资产概览+持仓列表合并', date: '04-08' },
              { hash: '4b1c750', msg: 'fix: 统一库存市值计算', date: '04-06' },
            ],
          },
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

    // ══════════════════════════════════════════════════════════════════════
    //  Chart visual helpers (theme-aware, ported from Demo B)
    // ══════════════════════════════════════════════════════════════════════
    const _cvIsDark = () => !document.documentElement.classList.contains('light');
    const _cvCss = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    const _cvGrid = () => _cvCss('--cv-border') || 'rgba(51,65,85,0.4)';
    const _cvTick = () => _cvCss('--cv-muted') || '#64748b';
    const _CV = { emerald: '#10b981', blue: '#3b82f6', amber: '#f59e0b', red: '#ef4444', pink: '#ec4899', purple: '#8b5cf6', cyan: '#06b6d4' };
    const _CV_PALETTE = [_CV.blue, _CV.amber, _CV.emerald, _CV.purple, _CV.red, _CV.pink, _CV.cyan, '#a855f7'];
    const _CV_FONT = 'ui-monospace, monospace';

    const _cvTtStyle = () => ({
      backgroundColor: _cvIsDark() ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.97)',
      titleColor: _cvIsDark() ? '#e2e8f0' : '#0f172a',
      bodyColor: _cvIsDark() ? '#cbd5e1' : '#334155',
      borderColor: _cvGrid(), borderWidth: 1, padding: 10,
      bodyFont: { family: _CV_FONT, size: 11 }, cornerRadius: 8,
    });
    const _cvLegend = (pos = 'top') => ({
      position: pos, align: 'start',
      labels: { color: _cvTick(), font: { size: 10, family: _CV_FONT }, usePointStyle: true, pointStyle: 'circle', boxWidth: 7, padding: 12 },
    });
    const _cvAxisX = () => ({
      ticks: { color: _cvTick(), font: { size: 9, family: _CV_FONT }, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
      grid: { color: _cvGrid(), drawBorder: false },
    });
    const _cvAxisY = (extra = {}) => ({
      ticks: { color: _cvTick(), font: { size: 9, family: _CV_FONT }, ...extra },
      grid: { color: _cvGrid(), drawBorder: false },
    });
    const _cvBase = () => ({
      responsive: true, maintainAspectRatio: false, resizeDelay: 100,
      animation: { duration: 500, easing: 'easeOutQuart' },
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: _cvLegend(), tooltip: _cvTtStyle() },
    });
    function _cvAreaGrad(ctx, area, hex) {
      const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
      g.addColorStop(0, hex + '40'); g.addColorStop(1, hex + '00'); return g;
    }
    function _cvBarGrad(ctx, area, hex) {
      const g = ctx.createLinearGradient(0, area.bottom, 0, area.top);
      g.addColorStop(0, hex + '35'); g.addColorStop(1, hex + 'bb'); return g;
    }
    function _cvRichLine(label, data, color, { axis = 'y', fill = false, width = 2.5 } = {}) {
      return {
        label, data, yAxisID: axis, borderColor: color,
        backgroundColor: fill ? (c) => { const a = c.chart.chartArea; return a ? _cvAreaGrad(c.chart.ctx, a, color) : null; } : 'transparent',
        fill, borderWidth: width, tension: 0.45, cubicInterpolationMode: 'monotone',
        pointRadius: 0, pointHoverRadius: 4,
        pointBackgroundColor: color, pointBorderColor: _cvIsDark() ? '#0f172a' : '#fff', pointBorderWidth: 2,
      };
    }
    const _cvZeroLinePlugin = {
      id: 'zeroLine',
      afterDraw(chart) {
        const yScale = chart.scales.yMoney;
        if (!yScale) return;
        const y = yScale.getPixelForValue(0);
        if (y < yScale.top || y > yScale.bottom) return;
        const ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = _cvIsDark() ? 'rgba(148,163,184,0.35)' : 'rgba(71,85,105,0.3)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(chart.chartArea.left, y);
        ctx.lineTo(chart.chartArea.right, y);
        ctx.stroke();
        ctx.restore();
      },
    };
    const _cvFmtFull = v => { if (v == null) return '-'; const s = v < 0 ? '-' : ''; return s + '¥' + Math.abs(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    const _cvFmtMoney = v => { if (v == null) return ''; const a = Math.abs(v); const s = v < 0 ? '-' : ''; return s + '¥' + (a >= 1e4 ? (a / 1e4).toFixed(1) + '万' : a.toLocaleString()); };
    const _cvFmtPct = v => v == null ? '' : v.toFixed(2) + '%';
    const _cvFmtK = v => { if (v == null) return '-'; const a = Math.abs(v); const s = v < 0 ? '-' : ''; if (a >= 1e4) return s + '¥' + (a / 1e4).toFixed(1) + '万'; return s + '¥' + Math.round(a).toLocaleString(); };
    const _cvFmtTip = v => `<span title="${_cvFmtFull(v)}" style="cursor:help;border-bottom:.5px dashed var(--cv-muted2)">${_cvFmtK(v)}</span>`;

    function app() {
      return {
        activeTab: 'overview',
        mobileMenu: false,   // UI-only: mobile header "更多" drawer open state
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
        theme: localStorage.getItem('theme') ?? 'dark',

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
        itemLeaseIncome: null,       // 单品租赁实绩(v0.13)
        // v0.13.2 触摸设备:收益追踪表格的可编辑单元格改单击进入编辑
        // (手机浏览器无可靠 dblclick,此前 7 个字段在手机上全都改不了)
        isTouchDevice: (typeof window !== 'undefined') &&
          (('ontouchstart' in window) || (navigator.maxTouchPoints || 0) > 0),
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
        // 应用登录用户（v0.10.0 用户系统）；username 为空 = 未启用用户系统（本地开发）
        currentUser: { username: '', role: '' },
        pwModal: { show: false, oldPw: '', newPw: '', newPw2: '', saving: false, msg: '', ok: false },
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
        // Chart data from /api/dashboard/chart-data
        chartData: {},
        _chartInstances: {},
        _chartObservers: {},   // unified IO+RO lifecycle, keyed by chart id
        _chartsSetup: false,

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
          const [,,,,, marketStatus, alertData] = await Promise.all([
            this.loadOverview(),
            this.loadItems(),
            this.loadPortfolioHistory(),
            this.loadChartData(),
            this.loadTracker(),
            fetch('/api/youpin/market/status').then(r => r.ok ? r.json() : null).catch(() => null),
            fetch('/api/analysis/alerts?page_size=1&unread_only=true').then(r => r.ok ? r.json() : null).catch(() => null),
            this._loadAuthState(),
            this._checkToken(),
            this._loadCurrentUser(),
          ]);
          if (marketStatus?.status === 'running') {
            this.refreshing = true;
            this.refreshProgress = marketStatus.progress;
            this._startRefreshPoll();
          }
          if (alertData) this.unreadAlertCount = alertData.total || 0;
          // 懒加载 tracker 数据。图表渲染时机统一交给 _setupChartObservers
          // （ResizeObserver 在 tab 显示/旋屏时触发、IntersectionObserver 在滚入视口时触发），
          // 不再用 setTimeout 兜底。
          this.$watch('activeTab', (tab) => {
            if (tab === 'tracker' && this.trackerData.length === 0) this.loadTracker();
          });
          // 持久化用户偏好到 localStorage
          this.$watch('nameLang', v => localStorage.setItem('nameLang', v));
          this.$watch('memberLevel', v => localStorage.setItem('memberLevel', v));
          this.$watch('youpinMembership', v => localStorage.setItem('youpinMembership', v));
          // Apply saved theme
          if (this.theme === 'light') document.documentElement.classList.add('light');
          // 渲染概览统计卡 + 建立图表统一可见性/尺寸观察器（单一入口）
          this.$nextTick(() => {
            this.renderStatCards(); this._setupChartObservers(); this._syncHeaderH();
            this._clearSkeletons();   // 数据已到位:移除残留骨架(数据为空时显示干净空态)
          });
          // 顶栏实际高度 → CSS 变量（移动端 token 横幅 top 跟随，避免重叠）
          setTimeout(() => this._syncHeaderH(), 300);
          window.addEventListener('resize', () => this._syncHeaderH());
          window.addEventListener('orientationchange', () => setTimeout(() => this._syncHeaderH(), 200));
          this._setupAutoRefresh();   // 页面可见时定时静默刷新,切回标签页若数据过期立即刷新
          this._purgeAutofill();      // 清除浏览器把保存的用户名误填进搜索框(凭证 autofill 无视 autocomplete=off)
        },

        // ── 自动填充清除安全网（v0.13.1）────────────────────────────────
        // Chrome 密码管理器登录后会把用户名塞进它认定的"用户名候选框"(本站的搜索框),
        // 且无视 autocomplete=off。特征:autofill 直接写 DOM 值、不触发 input 事件,
        // 因此 Alpine 模型仍为空 —— 检测到该不一致即清除。前 3 秒多次检查(Chrome 可能延迟填)。
        _purgeAutofill() {
          const purge = () => {
            for (const [sel, model] of [
              ['input[name="item-filter"]', () => this.filters.search],
              ['input[name="analysis-item-search"]', () => this.analysisSearch],
            ]) {
              const el = document.querySelector(sel);
              if (el && el.value && !model()) el.value = '';
            }
          };
          [200, 600, 1200, 2000, 3000].forEach(ms => setTimeout(purge, ms));
        },

        // ── 数据保鲜（v0.12）────────────────────────────────────────────
        // 用户停留/切回页面时数据自动更新,无需手动刷新;后端有 TTL 缓存,代价极小
        _AUTO_REFRESH_MS: 5 * 60 * 1000,
        _lastDataRefresh: 0,
        _setupAutoRefresh() {
          this._lastDataRefresh = Date.now();
          const stale = () => Date.now() - this._lastDataRefresh >= this._AUTO_REFRESH_MS;
          const refresh = async () => {
            this._lastDataRefresh = Date.now();
            try {
              await Promise.all([this.loadOverview(), this.loadChartData(), this.loadPortfolioHistory()]);
              this.renderStatCards();
            } catch (e) { console.warn('auto refresh error:', e); }
          };
          setInterval(() => { if (!document.hidden && stale()) refresh(); }, 60 * 1000);
          document.addEventListener('visibilitychange', () => {
            if (!document.hidden && stale()) refresh();
          });
        },

        _clearSkeletons() {
          document.querySelectorAll('.aur-skel-card, .aur-skel-tile').forEach(e => e.remove());
          document.querySelectorAll('.aur-skel-chart').forEach(e => e.classList.remove('aur-skel-chart'));
        },

        _syncHeaderH() {
          const h = document.querySelector('header');
          if (h) document.documentElement.style.setProperty('--hdr-h', h.offsetHeight + 'px');
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

        // ── 应用登录用户（v0.10.0 用户系统）─────────────────────────────
        async _loadCurrentUser() {
          try {
            const r = await fetch('/api/auth/me');
            if (r.ok) this.currentUser = await r.json();
          } catch (e) { /* 未启用用户系统时 404/网络错误均忽略 */ }
        },
        async changeAppPassword() {
          const m = this.pwModal;
          m.msg = ''; m.ok = false;
          if (m.newPw.length < 8) { m.msg = this.nameLang==='cn' ? '新密码至少 8 位' : 'New password must be at least 8 characters'; return; }
          if (m.newPw !== m.newPw2) { m.msg = this.nameLang==='cn' ? '两次输入的新密码不一致' : 'New passwords do not match'; return; }
          m.saving = true;
          try {
            const r = await fetch('/api/auth/change-password', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ old_password: m.oldPw, new_password: m.newPw }),
            });
            const data = await r.json().catch(() => ({}));
            if (r.ok) {
              m.ok = true;
              m.msg = this.nameLang==='cn' ? '密码已修改 ✓' : 'Password changed ✓';
              m.oldPw = m.newPw = m.newPw2 = '';
              setTimeout(() => { m.show = false; m.msg = ''; }, 1200);
            } else {
              m.msg = data.detail || (this.nameLang==='cn' ? '修改失败' : 'Change failed');
            }
          } catch (e) {
            m.msg = this.nameLang==='cn' ? '网络错误' : 'Network error';
          } finally { m.saving = false; }
        },
        async logoutApp() {
          try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {}
          window.location.href = '/login';
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
          await Promise.all([this.loadOverview(), this.loadItems(), this.loadPortfolioHistory(), this.loadMonitorStatus(), this.loadChartData()]);
          this.renderStatCards();
          this.renderOverviewCharts();
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
          const w = el.offsetWidth;
          if (!w) return;  // RED LINE: width 0 → bail, never create, never cache
          if (this.trackerGranularity !== 'hourly' && !this.trackerData?.length) return;
          const isMobile = window.matchMedia('(max-width: 640px)').matches;
          const isTouch = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;
          const dark = _cvIsDark();
          const fingerprint = 'tk:' + this.trackerChartType + ':' + this.trackerGranularity + ':' + this.trackerData.length + ':' + (dark ? 'dk' : 'lt');
          if (this._trackerChart && el.__fingerprint === fingerprint) return;
          if (this._trackerChart) { this._trackerChart.destroy(); this._trackerChart = null; }

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
              toolbar: { show: !isMobile, offsetY: -5, tools: { download: false, selection: false, zoom: true, zoomin: true, zoomout: true, pan: true, reset: true } },
              zoom: { enabled: !isTouch, type: 'x', autoScaleYaxis: true },
              fontFamily: 'ui-monospace, monospace',
            },
            series: [{ name: label, data: series }],
            stroke: { curve: 'smooth', width: 2 },
            fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.25, opacityTo: 0.02 } },
            colors: [_CV.blue],
            dataLabels: { enabled: false },
            xaxis: { type: 'category', labels: { style: { colors: _cvTick(), fontSize: '10px' }, rotate: 0, hideOverlappingLabels: true }, tickAmount: 10, axisBorder: { show: false }, axisTicks: { show: false } },
            yaxis: { labels: { style: { colors: _cvTick(), fontSize: '10px' }, formatter: fmtY } },
            grid: { borderColor: _cvGrid(), strokeDashArray: 3, padding: { left: 5, right: 5 } },
            tooltip: { theme: dark ? 'dark' : 'light', y: { formatter: fmtTip } },
            theme: { mode: dark ? 'dark' : 'light' },
          });
          this._trackerChart.render();
          el.__fingerprint = fingerprint;  // cache ONLY after a successful w>0 render

          // 滚轮缩放 X 轴 — 仅桌面（触摸设备无 wheel 事件，跳过死代码）
          if (!isTouch) {
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
          }
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
            // 数据更新后直接重绘（宽度守卫：不可见则 no-op，观察器会在可见时补绘）
            this.$nextTick(() => { try { this.renderPortfolioChart(); } catch(e) { console.warn('Portfolio chart error:', e); } });
          } catch (e) { this.showToast(e.message || '加载持仓历史失败', 'error'); }
        },

        renderPortfolioChart() {
          const canvas = document.getElementById('portfolioChart');
          if (!canvas) return;
          const w = (canvas.parentElement || canvas).offsetWidth;
          if (!w) return;  // RED LINE: width 0 → bail, never create, never cache
          // 指纹只含 数据+主题，不含宽度：resize 交给 Chart.js 原生 responsive，避免双重重建竞态
          const fingerprint = this.portfolioCategory + ':' + (this.portfolioCategory === 'value' ? this.portfolioData.length : this.trackerData.length) + ':' + (_cvIsDark() ? 'dk' : 'lt');
          if (canvas.__chart && canvas.__fingerprint === fingerprint) return;
          if (canvas.__chart) { canvas.__chart.destroy(); canvas.__chart = null; }
          const ctx = canvas.getContext('2d');
          if (!ctx) return;

          if (this.portfolioCategory === 'value') {
            const data = this.portfolioData;
            if (!data.length) return;
            const labels = data.map(d => {
              const dt = new Date(d.timestamp);
              return dt.toLocaleString('en-US', { timeZone:'America/Los_Angeles', month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false });
            });
            canvas.__chart = new Chart(ctx, {
              type: 'line',
              data: { labels, datasets: [
                _cvRichLine(this.t('market_value'), data.map(d => d.market_value), _CV.emerald, { axis: 'yMoney' }),
                _cvRichLine(this.t('total_cost'),   data.map(d => d.total_cost),   _CV.blue,    { axis: 'yMoney', width: 2 }),
                _cvRichLine(this.t('pnl_amount'),   data.map(d => d.pnl),          _CV.amber,   { axis: 'yMoney', width: 1.5 }),
                _cvRichLine(this.t('chart_pnl_pct'),data.map(d => d.pnl_pct),      _CV.red,     { axis: 'yPct',   width: 1.5 }),
              ]},
              plugins: [_cvZeroLinePlugin],
              options: {
                ..._cvBase(),
                plugins: { ..._cvBase().plugins,
                  tooltip: { ..._cvTtStyle(), callbacks: { label: c => c.dataset.label + ': ' + (c.datasetIndex === 3 ? _cvFmtPct(c.raw) : _cvFmtFull(c.raw)) } },
                },
                scales: {
                  x: _cvAxisX(),
                  yMoney: { position: 'left', ..._cvAxisY({ callback: _cvFmtMoney }) },
                  yPct: { position: 'right', ticks: { color: _CV.red, font: { size: 9, family: _CV_FONT }, callback: v => _cvFmtPct(v) }, grid: { drawOnChartArea: false } },
                },
              },
            });
          } else {
            const data = [...this.trackerData].reverse();
            if (!data.length) return;
            const labels = data.map(d => d.date);
            canvas.__chart = new Chart(ctx, {
              type: 'line',
              data: { labels, datasets: [
                _cvRichLine(this.t('tracker_col_combined'), data.map(d => d.combined_annual != null ? +(d.combined_annual * 100).toFixed(2) : null), _CV.emerald, { axis: 'yPct', fill: true }),
                _cvRichLine(this.t('tracker_col_income'),   data.map(d => d.daily_income),  _CV.amber, { axis: 'yRight', width: 2 }),
                _cvRichLine(this.t('tracker_col_rented'),   data.map(d => d.rented_count),  _CV.blue,  { axis: 'yRight', width: 1.5 }),
                _cvRichLine(this.t('chart_rented_value'),   data.map(d => d.rented_value),  _CV.pink,  { axis: 'yValue', width: 1.5 }),
              ]},
              options: {
                ..._cvBase(),
                plugins: { ..._cvBase().plugins,
                  tooltip: { ..._cvTtStyle(), callbacks: { label: c => { const v = c.raw; const i = c.datasetIndex; return c.dataset.label + ': ' + (i === 0 ? _cvFmtPct(v) : i === 2 ? (v??0)+' 件' : _cvFmtFull(v)); } } },
                },
                scales: {
                  x: _cvAxisX(),
                  yPct: { position: 'left', ticks: { color: _CV.emerald, font: { size: 9, family: _CV_FONT }, callback: v => _cvFmtPct(v) }, grid: { color: _cvGrid(), drawBorder: false } },
                  yRight: { position: 'right', ticks: { color: _CV.amber, font: { size: 9, family: _CV_FONT }, callback: _cvFmtMoney }, grid: { drawOnChartArea: false } },
                  yValue: { display: false },
                },
              },
            });
          }
          canvas.__fingerprint = fingerprint;  // cache ONLY after a successful w>0 render
        },

        // ── Chart Data (new visualizations) ──────────────────────────────
        async loadChartData() {
          try {
            const r = await fetch('/api/dashboard/chart-data');
            if (r.ok) {
              this.chartData = await r.json();
              // 数据到达后重绘概览图（宽度守卫：不可见则 no-op）
              this.$nextTick(() => { try { this.renderOverviewCharts(); } catch(e) { console.warn('Overview chart error:', e); } });
            }
          } catch (e) { console.warn('Chart data load failed:', e.message); }
        },

        renderStatCards() {
          const el = document.getElementById('statCards');
          if (!el || !this.overview.total_active) return;
          const o = this.overview;
          const t = this.trackerData?.[0] || {};
          const sb = o.status_breakdown || {};
          const cb = o.cost_breakdown || {};
          const total = o.total_active || 0;
          const rented = sb.rented_out || 0;
          const steam = sb.in_steam || 0;
          const rentedPct = total ? Math.round(rented / total * 100) : 0;
          const steamPct = total ? Math.round(steam / total * 100) : 0;
          const pnlColor = (o.pnl || 0) >= 0 ? _CV.emerald : _CV.red;
          const coveragePct = o.coverage_pct || 0;
          const pricedCount = o.priced_count || 0;
          const unpricedCount = o.unpriced_count || 0;
          const dot = (color, label) => `<span style="color:${color}">●</span> ${label}`;

          el.innerHTML = `
            <div class="glass-solid stat-card" style="padding:16px; border-radius:var(--cv-r);">
              <div style="font-size:10px;color:var(--cv-muted);">持仓市值</div>
              <div style="font-size:22px;font-weight:800;letter-spacing:-.8px;color:${_CV.emerald};margin:4px 0;">
                ${_cvFmtFull(o.market_value)}</div>
              <div style="font-size:10px;color:var(--cv-muted);display:flex;justify-content:space-between;">
                <span>库存 ${_cvFmtTip(o.market_value_steam)}</span>
                <span>出租 ${_cvFmtTip(o.market_value_rented)}</span>
              </div>
              <div style="margin-top:8px;font-size:9px;color:var(--cv-muted2);">
                ${dot(_CV.purple, `出租中 ${rented.toLocaleString()} (${rentedPct}%)`)}
                &nbsp;${dot(_CV.blue, `Steam ${steam.toLocaleString()} (${steamPct}%)`)}
                &nbsp;· 共 ${total.toLocaleString()} 件
              </div>
            </div>
            <div class="glass-solid stat-card" style="padding:16px; border-radius:var(--cv-r);">
              <div style="font-size:10px;color:var(--cv-muted);">持仓成本 & 定价</div>
              <div style="font-size:22px;font-weight:800;letter-spacing:-.8px;color:${_CV.blue};margin:4px 0;">
                ${_cvFmtFull(o.total_cost)}</div>
              <div style="font-size:10px;color:var(--cv-muted);display:flex;justify-content:space-between;">
                <span>出租 ${_cvFmtTip(cb.rented_out)}</span>
                <span>Steam ${_cvFmtTip(cb.in_steam)}</span>
              </div>
              <div style="margin-top:8px;font-size:9px;color:var(--cv-muted2);">
                定价覆盖 <span style="color:${coveragePct > 80 ? _CV.emerald : _CV.amber}">${coveragePct}%</span>
                · 已定价 ${pricedCount.toLocaleString()} · 未定价 <span style="color:${_CV.amber}">${unpricedCount.toLocaleString()}</span>
              </div>
            </div>
            <div class="glass-solid stat-card" style="padding:16px; border-radius:var(--cv-r);">
              <div style="font-size:10px;color:var(--cv-muted);">盈亏</div>
              <div style="font-size:22px;font-weight:800;letter-spacing:-.8px;color:${pnlColor};margin:4px 0;">
                ${(o.pnl >= 0 ? '+' : '') + _cvFmtFull(o.pnl)}</div>
              <div style="font-size:14px;font-weight:700;color:${pnlColor};">
                ${(o.pnl_pct >= 0 ? '+' : '') + (o.pnl_pct || 0).toFixed(2)}%</div>
              <div style="margin-top:6px;font-size:9px;color:var(--cv-muted2);">
                基于 ${(o.pnl_covered_count || o.market_priced_count || 0).toLocaleString()} 件已定价持仓
              </div>
            </div>
            <div class="glass-solid stat-card" style="padding:16px; border-radius:var(--cv-r);">
              <div style="font-size:10px;color:var(--cv-muted);">租赁收益</div>
              <div style="font-size:22px;font-weight:800;letter-spacing:-.8px;color:${_CV.amber};margin:4px 0;">
                ${_cvFmtFull(t.daily_income)}<span style="font-size:12px;font-weight:400;color:var(--cv-muted);"> /日</span></div>
              <div style="font-size:14px;font-weight:700;color:${_CV.amber};">
                年化 ${((t.combined_annual || 0) * 100).toFixed(1)}%</div>
              <div style="margin-top:6px;font-size:9px;color:var(--cv-muted2);">
                出租 ${rented.toLocaleString()} 件 · 件均 ¥${(t.income_per_item || 0).toFixed(2)}/日
              </div>
            </div>`;
        },

        _destroyOverviewCharts() {
          ['doughnut', 'rank', 'dist'].forEach(k => {
            if (this._chartInstances[k]) { this._chartInstances[k].destroy(); delete this._chartInstances[k]; }
          });
        },

        // ── Unified chart lifecycle (single entry) ──────────────────────
        // Width-0 renders skipped & never cached (B1/B2 red line). On size change
        // (rotation/tab reflow) ResizeObserver lets the chart libs resize natively
        // (no destroy/recreate → no Chart.js responsive race). On scroll-into-view
        // IntersectionObserver FORCE-repaints Chart.js instances: iOS WebKit drops
        // the backing store of off-screen canvases, so a chart drawn while below
        // the fold shows blank and never auto-redraws — re-render() when it becomes
        // visible fixes it. If no instance yet, create it (now that it's on-screen).
        _renderWhenVisible(observeEl, key, fn) {
          if (!observeEl) return;
          const safe = () => { try { fn(); } catch (e) { console.warn('chart ' + key, e); } };
          safe();                                // immediate attempt — no-op if width 0
          if (this._chartObservers[key]) return; // attach observers once per element
          const rec = {};
          if ('ResizeObserver' in window) {
            let t;
            rec.ro = new ResizeObserver(() => { clearTimeout(t); t = setTimeout(safe, 150); });
            rec.ro.observe(observeEl);
          }
          if ('IntersectionObserver' in window) {
            rec.io = new IntersectionObserver((es) => {
              for (const e of es) {
                if (!e.isIntersecting) continue;
                const inst = this._chartFor(key);
                if (!inst) { safe(); }                                   // not built yet → build on-screen
                else if (inst.canvas && typeof inst.render === 'function') {
                  try { inst.render(); } catch (_) {}                    // Chart.js: force repaint (iOS off-screen fix)
                }
              }
            }, { threshold: 0.01, rootMargin: '250px' });
            rec.io.observe(observeEl);
          }
          this._chartObservers[key] = rec;
        },
        // live chart instance for a given key (Chart.js have .canvas; ApexCharts don't)
        _chartFor(key) {
          if (key === 'portfolio') return document.getElementById('portfolioChart')?.__chart;
          if (key === 'doughnut' || key === 'rank' || key === 'dist') return this._chartInstances[key];
          if (key === 'tracker') return this._trackerChart;
          if (key === 'price') return this._priceChart;
          return null;
        },
        // wrapper element (fixed-height div) of a canvas chart, used for width measure + observation
        _chartWrap(id) { const c = document.getElementById(id); return c ? (c.parentElement || c) : null; },
        _setupChartObservers() {
          if (this._chartsSetup) return;
          this._chartsSetup = true;
          this._renderWhenVisible(this._chartWrap('portfolioChart'), 'portfolio', () => this.renderPortfolioChart());
          this._renderWhenVisible(this._chartWrap('doughnutChart'),  'doughnut',  () => this._renderDoughnut());
          this._renderWhenVisible(this._chartWrap('rankChart'),      'rank',      () => this._renderRank());
          this._renderWhenVisible(this._chartWrap('distChart'),      'dist',      () => this._renderDist());
          this._renderWhenVisible(document.getElementById('trackerChart'), 'tracker', () => this.renderTrackerChart());
          this._renderWhenVisible(document.getElementById('priceChart'),   'price',   () => this.renderPriceChart());
        },

        renderOverviewCharts() {
          if (!this.chartData?.type_composition) return;
          this._renderDoughnut();
          this._renderTopGrid();
          this._renderRank();
          this._renderDist();
        },

        _renderDoughnut() {
          const canvas = document.getElementById('doughnutChart');
          const types = this.chartData.type_composition;
          if (!canvas || !types?.length) return;
          const w = (canvas.parentElement || canvas).offsetWidth;
          if (!w) return;  // RED LINE: width 0 → bail, never create, never cache
          const lm = { '非凡 手套': '手套', '隐秘 步枪': '步枪(隐秘)', '隐秘 匕首': '匕首', '保密 步枪': '步枪(保密)',
            '隐秘 手枪': '手枪', '隐秘 狙击步枪': '狙击(隐秘)', '保密 狙击步枪': '狙击(保密)', '卓越 探员': '探员',
            '受限 步枪': '步枪(受限)', '高级 探员': '探员(高级)', '工业级 步枪': '步枪(工业)', '大师 探员': '探员(大师)',
            '其他': '其他', 'N/A': '其他' };
          const labels = types.map(t => lm[t.type] || t.type);
          const values = types.map(t => Math.round(t.market_value));
          const fp = 'dn:' + values.reduce((a, b) => a + b, 0) + ':' + (_cvIsDark() ? 'dk' : 'lt');
          if (this._chartInstances.doughnut && canvas.__fp === fp) return;
          if (this._chartInstances.doughnut) this._chartInstances.doughnut.destroy();
          canvas.__fp = fp;
          this._chartInstances.doughnut = new Chart(canvas.getContext('2d'), {
            type: 'doughnut',
            data: { labels, datasets: [{ data: values, backgroundColor: labels.map((_, i) => _CV_PALETTE[i % _CV_PALETTE.length]), borderWidth: 0, hoverOffset: 6 }] },
            options: {
              responsive: true, maintainAspectRatio: false, cutout: '55%',
              animation: { animateRotate: true, duration: 600 },
              plugins: {
                legend: _cvLegend('right'),
                tooltip: { ..._cvTtStyle(), callbacks: { label: c => { const t = c.dataset.data.reduce((s, x) => s + x, 0) || 1; return c.label + ': ' + _cvFmtFull(c.parsed) + ' (' + Math.round(c.parsed / t * 100) + '%)'; } } },
              },
            },
          });
        },

        _chartIcon(url) {
          if (!url) return '/static/placeholder.svg';
          if (url.startsWith('http')) return url;
          return `https://community.fastly.steamstatic.com/economy/image/${url}/128fx128f`;
        },
        _renderTopGrid() {
          const items = this.chartData.top_value;
          const el = document.getElementById('topGrid');
          if (!el || !items?.length) return;
          const cardHtml = items.map(i => {
            const icon = this._chartIcon(i.icon_url);
            let name = i.cn_name || i.name;
            if (name && name.length > 20) name = name.slice(0, 18) + '…';
            const pnlColor = (i.pnl || 0) >= 0 ? _CV.emerald : _CV.red;
            return `<div class="item-card">
              <img src="${icon}" alt="" loading="lazy" onerror="this.src='/static/placeholder.svg'">
              <div class="item-name">${name || '—'}</div>
              <div class="item-val" style="color:${pnlColor}" title="${_cvFmtFull(i.market_value)}">${_cvFmtK(i.market_value)}</div>
              <div class="item-qty">×${i.qty}</div>
            </div>`;
          }).join('');
          const n = items.length;
          const divisors = [];
          for (let c = 5; c <= n; c++) { if (n % c === 0) divisors.push(c); }
          const doLayout = () => {
            const w = el.offsetWidth || el.parentElement?.offsetWidth || 0;
            if (w < 10) { requestAnimationFrame(doLayout); return; }
            const ideal = Math.floor(w / 110);
            let cols = divisors.length ? divisors.reduce((best, d) => Math.abs(d - ideal) < Math.abs(best - ideal) ? d : best) : ideal;
            cols = Math.max(5, Math.min(n, cols));
            el.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
            el.innerHTML = cardHtml;
          };
          requestAnimationFrame(doLayout);
          if (!this._topGridResizeBound) {
            this._topGridResizeBound = true;
            let timer;
            window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(() => { if (this.activeTab === 'overview') this._renderTopGrid(); }, 150); });
          }
        },

        _renderRank() {
          const canvas = document.getElementById('rankChart');
          const gainers = this.chartData.top_gainers || [];
          const losers = this.chartData.top_losers || [];
          if (!canvas) return;
          const w = (canvas.parentElement || canvas).offsetWidth;
          if (!w) return;  // RED LINE: width 0 → bail, never create, never cache
          const combined = [...[...gainers].reverse(), ...losers];  // 不原地 reverse，避免污染 chartData
          if (!combined.length) return;
          const labels = combined.map(i => { let s = i.cn_name || i.name || ''; return s.length > 18 ? s.slice(0, 16) + '…' : s; });
          const values = combined.map(i => i.pnl);
          const fp = 'rk:' + values.reduce((a, b) => a + (b || 0), 0) + ':' + values.length + ':' + (_cvIsDark() ? 'dk' : 'lt');
          if (this._chartInstances.rank && canvas.__fp === fp) return;
          if (this._chartInstances.rank) this._chartInstances.rank.destroy();
          canvas.__fp = fp;
          this._chartInstances.rank = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: { labels, datasets: [{ data: values,
              backgroundColor: c => { const a = c.chart.chartArea; if (!a) return (c.raw >= 0 ? _CV.emerald : _CV.red) + '80'; return _cvBarGrad(c.chart.ctx, a, c.raw >= 0 ? _CV.emerald : _CV.red); },
              borderColor: c => c.raw >= 0 ? _CV.emerald : _CV.red,
              borderWidth: 1.5, borderRadius: 5, borderSkipped: false,
            }]},
            options: { ..._cvBase(), indexAxis: 'y',
              plugins: { legend: { display: false }, tooltip: { ..._cvTtStyle(), callbacks: { label: c => _cvFmtFull(c.raw) } } },
              scales: { x: { ..._cvAxisY({ callback: _cvFmtMoney }), position: 'top' }, y: { ticks: { color: _cvTick(), font: { size: 9, family: _CV_FONT } }, grid: { display: false } } },
            },
          });
        },

        _renderDist() {
          const canvas = document.getElementById('distChart');
          const dist = this.chartData.pnl_distribution;
          if (!canvas || !dist) return;
          const w = (canvas.parentElement || canvas).offsetWidth;
          if (!w) return;  // RED LINE: width 0 → bail, never create, never cache
          const bL = ['<-50%', '-50~-30%', '-30~-10%', '-10~0%', '0~10%', '10~30%', '30~50%', '50~100%', '>100%'];
          const bK = ['<-50', '-50~-30', '-30~-10', '-10~0', '0~10', '10~30', '30~50', '50~100', '>100'];
          const vals = bK.map(k => dist[k] || 0);
          const cols = bK.map((_, i) => i < 4 ? _CV.red : i === 4 ? (_cvIsDark() ? '#64748b' : '#94a3b8') : _CV.emerald);
          const fp = 'ds:' + vals.join(',') + ':' + (_cvIsDark() ? 'dk' : 'lt');
          if (this._chartInstances.dist && canvas.__fp === fp) return;
          if (this._chartInstances.dist) this._chartInstances.dist.destroy();
          canvas.__fp = fp;
          this._chartInstances.dist = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: { labels: bL, datasets: [{ data: vals,
              backgroundColor: c => { const a = c.chart.chartArea; if (!a) return cols[c.dataIndex] + '80'; return _cvBarGrad(c.chart.ctx, a, cols[c.dataIndex]); },
              borderColor: cols, borderWidth: 1.5, borderRadius: 5, borderSkipped: false, maxBarThickness: 36,
            }]},
            options: { ..._cvBase(),
              plugins: { legend: { display: false }, tooltip: { ..._cvTtStyle(), callbacks: { label: c => c.raw + ' 个品类' } } },
              scales: { x: { ..._cvAxisX(), grid: { display: false } }, y: _cvAxisY() },
            },
          });
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
          // v0.13.3：此前用 querySelector('.tbl-wrap') 取到的是**上架页**的表格
          // (文档中第一个匹配),持仓表在后面 → 桌面滚了个 display:none 的元素、
          // 手机上 .tbl-wrap{max-height:none} 根本没有内部滚动 → 翻页后仍停在页尾。
          // 改为滚动持仓区自身;移动端卡片列表没有内部滚动容器,退化为滚窗口。
          const wrap = document.querySelector('.holdings-table-wrap');
          if (wrap && wrap.scrollHeight > wrap.clientHeight) {
            wrap.scrollTo({ top: 0, behavior: 'smooth' });
          } else {
            document.getElementById('statCards')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
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
            this.renderStatCards();
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
          // v0.13.3：加失败熔断。此前 !r.ok 直接 return、catch 里还在 setInterval 内
          // 弹 toast → 后端一抖动就每 2.5 秒弹一次错误、永不停止,且 refreshing 永为 true
          // 让「刷新市价」按钮直到刷新页面前一直不可用。
          let fails = 0;
          const giveUp = (msg) => {
            clearInterval(this._refreshPollTimer);
            this.refreshing = false;
            this.showToast(msg, 'error');   // 只弹一次
          };
          this._refreshPollTimer = setInterval(async () => {
            try {
              const r = await fetch('/api/youpin/market/status');
              if (!r.ok) {
                if (++fails >= 5) giveUp('刷新状态查询持续失败,已停止轮询');
                return;
              }
              fails = 0;
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
            } catch (e) {
              if (++fails >= 5) giveUp('刷新轮询失败：' + (e.message || e));
            }
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

        // v0.13.3：此前无 ok 检查也无 catch —— 服务端 500 或断网时,本地照样把
        // is_read 翻成 true 并扣角标(服务端根本没收到),刷新后"已读"又变回未读。
        async markAlertRead(a) {
          try {
            const r = await fetch(`/api/analysis/alerts/${a.id}/read`, { method: 'PATCH' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            a.is_read = true;
            this.unreadAlertCount = Math.max(0, this.unreadAlertCount - 1);
          } catch (e) { this.showToast('标记已读失败：' + (e.message || e), 'error'); }
        },

        async markAllAlertsRead() {
          try {
            const r = await fetch('/api/analysis/alerts/read-all', { method: 'POST' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            this.analysisAlerts.items.forEach(a => a.is_read = true);
            this.unreadAlertCount = 0;
          } catch (e) { this.showToast('全部已读失败：' + (e.message || e), 'error'); }
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
          this.itemLeaseIncome = null;
          try {
            // 信号 + 租赁实绩(v0.13)并行拉取
            const [r, li] = await Promise.all([
              fetch(`/api/analysis/signals?market_hash_name=${encodeURIComponent(name)}&days=${this.chartDays}`),
              fetch(`/api/analysis/lease-income?market_hash_name=${encodeURIComponent(name)}&days=30`).catch(() => null),
            ]);
            if (r.ok) {
              this.itemSignals = await r.json();
              this.$nextTick(() => this.renderPriceChart());
            }
            if (li && li.ok) this.itemLeaseIncome = await li.json();
          } catch (e) { this.showToast(e.message || '加载信号数据失败', 'error'); }
        },

        renderPriceChart() {
          const el = document.getElementById('priceChart');
          if (!el || !this.itemSignals?.chart_data?.length) return;
          const cw = el.offsetWidth;
          if (!cw) return;  // RED LINE: width 0 → bail, never create, never cache

          const raw = this.itemSignals.chart_data;
          const isDark = _cvIsDark();
          const textColor = _cvTick();
          const gridColor = _cvGrid();

          // 时间范围过滤
          let data = raw;
          if (this.chartDays > 0) {
            const cutoff = Date.now() - this.chartDays * 86400e3;
            data = raw.filter(d => { const s=d.date; return new Date(s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)).getTime() >= cutoff; });
          }
          const fp = 'pc:' + (this.itemSignals.market_hash_name || '') + ':' + this.chartDays + ':' + data.length + ':' + (isDark ? 'dk' : 'lt');
          if (this._priceChart && el.__fingerprint === fp) return;
          if (this._priceChart) { this._priceChart.destroy(); this._priceChart = null; }
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
            legend: { labels: { colors: textColor }, fontSize: '10px', markers: { width: 10, height: 10 } },
            tooltip: { theme: isDark ? 'dark' : 'light', shared: true, intersect: false },
            theme: { mode: isDark ? 'dark' : 'light' },
          });
          this._priceChart.render();
          el.__fingerprint = fp;  // cache ONLY after a successful w>0 render
        },

        async triggerBackfill() {
          this.backfillRunning = true;
          this.backfillProgress = '启动中…';
          try {
            const start = await fetch('/api/analysis/backfill', { method: 'POST' });
            if (!start.ok) throw new Error(`HTTP ${start.status}`);
            // v0.13.3：加失败熔断 + 安全超时。此前无 r.ok 检查、bf 为 undefined 时
            // 抛进 catch 只 console.warn,3s 轮询永不停 → 按钮永久卡在「回填中…」。
            let fails = 0;
            const stop = (msg, type) => {
              clearInterval(poll); clearTimeout(guard);
              this.backfillRunning = false;
              if (msg) this.showToast(msg, type || 'error');
            };
            const poll = setInterval(async () => {
              try {
                const r = await fetch('/api/analysis/collector/status');
                if (!r.ok) { if (++fails >= 5) stop('回填状态查询持续失败,已停止轮询'); return; }
                const d = await r.json();
                const bf = d.backfill;
                if (!bf) { if (++fails >= 5) stop('回填状态缺失,已停止轮询'); return; }
                fails = 0;
                this.backfillProgress = `${bf.done}/${bf.total} ${bf.progress||''}`;
                if (bf.status !== 'running') {
                  stop(bf.status === 'done' ? '历史数据回填完成' : '回填异常: ' + bf.progress,
                       bf.status === 'done' ? 'success' : 'error');
                  this.loadAnalysis();
                }
              } catch (e) { if (++fails >= 5) stop('回填轮询失败：' + (e.message || e)); }
            }, 3000);
            const guard = setTimeout(() => stop('回填超时(20 分钟),已停止轮询'), 20 * 60 * 1000);
          } catch (e) {
            this.backfillRunning = false;
            this.showToast('回填启动失败：' + (e.message || e), 'error');
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
          // v0.13.3：此前这里只弹一句成功提示、根本不发请求(端点也不存在),
          // 用户以为采集已启动。现在真调 /api/analysis/collect-now 并如实反馈。
          try {
            const r = await fetch('/api/analysis/collect-now', { method: 'POST' });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
            this.showToast(d.message || (d.started ? '价格采集已启动（约 8 分钟）' : '采集已在运行中'),
                           d.started === false ? 'warning' : 'success');
          } catch (e) { this.showToast('价格采集触发失败：' + (e.message || e), 'error'); }
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

        toggleTheme(ev) {
          const next = this.theme === 'dark' ? 'light' : this.theme === 'light' ? 'system' : 'dark';
          this.theme = next;
          const apply = () => {
            if (next === 'system') {
              localStorage.removeItem('theme');
              const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches;
              document.documentElement.classList.toggle('light', !prefersDark);
            } else {
              localStorage.setItem('theme', next);
              document.documentElement.classList.toggle('light', next === 'light');
            }
          };
          // AURORA: View Transitions 圆形揭幕(从主题按钮位置扩散);不支持则瞬时切换
          if (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
            const x = ev?.clientX ?? innerWidth - 80, y = ev?.clientY ?? 28;
            const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
            const vt = document.startViewTransition(apply);
            vt.ready.then(() => {
              document.documentElement.animate(
                { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
                { duration: 520, easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
                  pseudoElement: '::view-transition-new(root)' },
              );
            }).catch(() => {});
          } else {
            apply();
          }
          // N1: 主题切换后重绘所有图表（指纹含有效主题 → 强制重建；隐藏的图宽度0自动 no-op）
          this._destroyOverviewCharts();
          this.$nextTick(() => {
            this.renderStatCards();
            this.renderPortfolioChart();
            this.renderOverviewCharts();
            this.renderTrackerChart();
            this.renderPriceChart();
          });
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
          if (!raw) return '/static/placeholder.svg';   // 同上：避免空 src 触发整页重取
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
          // 返回占位图而非 ''：空 src 会解析成当前文档 URL,浏览器会为每个无图行
          // 重新下载整个 HTML 页面(200 行 = 200 次文档请求),手机流量与解析开销都实打实。
          if (!url) return '/static/placeholder.svg';
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
