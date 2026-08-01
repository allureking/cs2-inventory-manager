# Changelog / 更新日志

## [0.13.4] - 2026-07-31

### 新增 / Added
- **手滑低价防线**：人工输入的价格低于该件当前市价 5% 以上时，先弹二次确认，确认后才
  提交。覆盖改价弹窗的四个价格字段（售价 / 日租金 / 长租日租金 / 押金）与三条人工路径
  （出售货架、出租货架、转租），以及 API 侧的手动上架端点 / **Fat-finger low-price guard**:
  a confirmation step when a manually entered price is more than 5% below market

  - 判据 `price < 基准 × 0.95`，由单一常数 `LOW_PRICE_CONFIRM_RATIO` 决定
  - 基准：售价取本地 `price_snapshot` 的跨平台最低价（免 token、免 HTTP，生产实测覆盖
    4282/4323 = **99.05%** 活跃持仓）；租金三项取悠悠市场挂租列表的最低报价（一次请求
    同时算出三个基准，4s 超时）
  - **拦在服务端**：前端弹窗只管体验，带 `X-API-Key` 的脚本会直接绕过前端。四个端点
    共用同一层校验，越线回 409 + 结构化 `violations`，带 `confirm_below_market=true`
    重发即放行
  - **一次列全所有越线字段**：确认是一次性全局豁免，只报第一条会让用户在不知情的情况下
    把另一项也放行了
  - **查不到基准就放行（fail-open）**：缺基准最集中的是「刚买入、当天还没进采价名单、
    第一次上架」的品，恰恰最需要能挂出去；这道防线没有安全属性，fail-closed 换不来
    保障只换来不可用。极端值另有硬闸兜底（`gt=0` / `_MAX_PRICE` / `_MAX_RENT`）
  - **是确认不是硬拦截**：`market_hash_name` 只区分磨损档位，不区分档内 float 与图案
    （蓝宝石、渐变、印花本），同名两件真实价值可差数倍。用一个已知会偏的基准做硬拦截
    是错配，可点穿的确认才是相称的强度
  - 沿用项目既有的原生 `confirm()` 范式，**不新增任何弹窗、不改动任何外观**

### 修复 / Fixed
- 出租改价分支此前连「日租金 > 0」都没校验，NaN 会被直接送到悠悠 / Lease reprice had no positivity check
- 确认文案在英文界面下中英混排（字段名与基准来源是服务端硬编码中文）→ 服务端改发
  机器可读键，文案完全在前端本地化 / Confirmation text is now fully localized
- 请求在途时关掉改价弹窗（取消 / Esc 都不会中止在途请求），409 返回后仍会弹确认并真的
  提交 → 提交前校验弹窗仍打开且仍是同一件 / Closing the modal mid-flight no longer submits
- 浏览器「阻止此页面创建更多对话框」被勾选后 `confirm()` 直接返回 false，形成无提示的
  死路（看起来像保存按钮坏了）→ 取消时给出回执 / Suppressed dialogs no longer dead-end silently
- 响应非 JSON（502 网关 HTML 错误页）时 `r.json()` 的异常会盖住真实状态；422 的数组型
  `detail` 会被拼成 `[object Object]` / Robust error surfacing on non-JSON and 422 responses

### 测试 / Tests
- 416 → **456** 用例。防线部分 40 例，含端点接线覆盖（此前所有用例只调内部 helper，
  把四个端点的防线调用全删掉也照样全绿）。6 次破坏性验证全部精确打红，浏览器实测 7 个
  交互场景零报错

## [0.13.3] - 2026-07-29

四路审查（后端 / 前端移动端 / 数据口径 / 安全）的修复收口。这一版几乎全是**静默错误**：
不报错、不崩溃，只是把错的数字端到你面前。

### 修复 / Fixed
- **「当前市价」口径静默漂移**（全站市值与 PnL）：写入侧有两条节奏不同的通路——日批把
  BUFF/STEAM/YOUPIN 三行写在同一 `snapshot_minute`，而「刷新市价」只写 YOUPIN 且逐件
  各 stamp 当前分钟。旧取价逻辑「取全局最新那一分钟再 MIN」于是在你点过一次刷新后，
  该件的跨平台最低价静默退化成悠悠单价，同一张概览上两种口径混用。改为**每个平台各取
  其最新报价再跨平台取 min**；陈旧报价用**相对**新鲜度窗（落后该件全平台最新 >72h 的
  平台剔除），而非绝对时间窗——绝对窗会在采集中断时让所有价格一起消失、持仓市值瞬间
  归零 / **Price basis drift**: "current price" is now per-platform-latest then cross-platform min, so a manual refresh no longer silently reduces it to YouPin-only
- **导入对账完整性闸**：悠悠返回空列表（code 9004001 被视为正常）或分页中途失败时，旧
  逻辑会无条件把全部 `rented_out` 置为 `unknown` 并提交——一次接口抖动就让 3800+ 件、
  约 ¥360 万在租资产从全站市值与成本中消失，且无任何告警。现在空响应/分页截断/抓取量
  显著少于 `totalCount` 时一律跳过对账并记录原因 / **Import reconcile guard** against wiping active leases on a flaky API response
- **出售导入非幂等**（可反复触发的持仓蚕食）：出售记录接口每次返回全量历史且记录里没有
  能定位到具体某一件的标识，旧实现「每条记录随手挑一件在库同名物品标 sold」又不留处理
  记号，于是每点一次全量导入就再吞掉一批还在库的物品。改为按名收敛对账（已 sold 先抵扣、
  只补差额、按 id 定序）。生产核查该 bug 尚未被触发，无需数据修复 / **Sell import is now idempotent** (converging per-name reconcile)
- **租赁实绩年化口径**：拆为「在租日年化」（在租时的赚钱效率）与「真实年化·含闲置」（按
  日历天摊薄的真实回报），并给出出租率；此前分母只数「有租记录的天数」，闲置期被自动
  剔除 → 恒报高位，出租率越差虚高越多。排行榜的件数改用**单日在租峰值**（此前用
  `COUNT(DISTINCT commodity_id)`，而同一物理饰品每个租赁周期都会换新 id，周转越快低估越狠）
  / **Lease yield metrics** split into rented-day vs. calendar-day annualized + utilization
- **收益追踪日快照的租赁侧失败**：此前只 log 一条 warning 就写出一行 `rented_count=0` /
  `daily_income=0` / 年化=0 的「当日数据」——在收益曲线上就是真真切切一天没租出去；且
  总市值 = 租赁价值 + 库存估值，租赁侧一挂总市值直接塌成只剩一成，画出一根凭空的暴跌。
  现在取不到就整组不写（不插 0、不覆盖已有值）并在 `notes` 留 `rental_stats=unavailable`
  / **Daily snapshot** no longer records a fake zero-income day when the lease API fails
- **短信登录丢失会员等级**：`sms_login` 漏了 `_runtime_member_level` 的 `global` 声明，赋值
  只写进函数局部；而返回值读的正是那个局部量、显示正确，于是持久化与后续读取一律为 0
  且完全不可见 / `sms_login` member level now actually persists
- **后台任务被 GC 静默吞掉**：CPython 对 `asyncio.create_task` 只持弱引用，任务可能在完成前
  被回收，留下 `cache["refreshing"]=True` 永久卡死估值缓存。新增 `app/core/tasks.spawn()`
  持强引用，替换全部 10 处裸调用 / Background tasks now hold strong refs
- 若干假成功交互：「立即采集」按钮此前根本不发请求；告警已读/全部已读不校验响应；轮询与
  回填无失败熔断（连续 5 次失败即停 + 20 分钟超时）；图片加载失败回落占位图 / Several fake-success UI actions fixed

### 安全 / Security
- **会话中间件改 fail-closed**：用户表为空时不再静默直通（`/api/*` 返回 503、页面 302），
  需要开放访问时显式设 `ALLOW_ANONYMOUS=1` / Session middleware is now fail-closed
- **上架/改价端点入参约束**：`/api/listing` 的 sell / lease / both / reprice / smart /
  batch-smart-reprice 会把价格**直接推到悠悠线上**，此前请求模型全是裸 float/int——0、负数、
  NaN、1e308 都能原样穿过去。现加 `gt=0` 与宽松上限、`max_days` 1–90、`mode` 枚举化、
  批量 30 件上限 / Money-touching listing endpoints now validate their inputs

### 移动端 / Mobile
- **持仓列表不再渲染两棵 DOM**：此前桌面表格与手机卡片同时构建、只用 CSS `display:none`
  藏掉一棵，手机上白白构建并持续响应式追踪那张从不显示的大表。改为 `x-if` 二选一（断点
  跨越时实时切换）/ Holdings list now renders one tree, not both
- 收益追踪表 7 个可编辑字段在手机上无法填写（只绑了 `@dblclick`，手机无可靠双击）→ 改为
  触摸端单击进入编辑；同步修 iOS 键盘不弹（`$nextTick` 会逃出手势上下文，改为同步 focus）
  与 <16px 输入框导致的整页放大 / Tracker's 7 editable cells are now editable on touch devices
- 子标签栏可横向滚动而非被裁切；分页按钮与复选框放大到可点尺寸；密码弹窗可滚动

### 测试 / Tests
- 301 → **416** 用例。本版新增的每一处修复都配了回归锁，并逐一做**破坏性验证**（把修复
  改回旧行为，确认对应用例精确变红），避免"空绿"

## [0.13.2] - 2026-07-28

### 修复 / Fixed
- 手机端收益追踪表的 7 个字段（在租件数/在租价值/日收入/总件数/库存价值/成本基准/大盘指数）
  完全无法填写：单元格只绑了 `@dblclick`，而手机浏览器没有可靠的双击事件 / Tracker cells were undeditable on mobile (dblclick-only)

## [0.13.1] - 2026-07-28

### 修复 / Fixed
- 概览的饰品搜索框每次强制刷新后被 Chrome 密码管理器自动填入用户名：`type="search"` +
  `autocomplete="off"` 挡不住，改为 readonly-until-focus + JS 兜底清除 / Search box no longer autofilled with the username
- 右上角用户区收纳为 👤 图标下拉菜单（用户名/改密/退出），释放顶栏空间 / User area collapsed into a 👤 menu

## [0.13.0] - 2026-06-11

### 新增 / Added
- **凭证哨兵**（提案6）：每日 23:55 PT + 启动时探测悠悠 Token，失效 → 预警中心 critical 告警（去重不刷屏）+ 日志 ERROR + 可选外推（`SERVERCHAN_KEY` / `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`，.env 配置即生效）；恢复后未读告警自动愈合 / **Credential sentinel** with in-app alert, optional push channels, auto-heal
- **单品租赁实绩归因**（提案9a）：新表 `lease_income_daily`，每日 00:01 PT + 租赁导入时落库每件在租饰品的日租金；API `/api/analysis/lease-income`（单品曲线+实际年化）与 `/lease-income/rankings`；单品分析页新增「租赁实绩·近30天」卡 / **Per-item lease income attribution**: daily recording, item curve + actual annualized + rankings API, new UI card
- **GitHub Actions CI**：push/PR 云端全量回归，与本地 pre-commit 双闸 / CI running full regression on push/PR

### 修复 / Fixed
- **成本找回**（提案5①）：磨损值精确指纹匹配（受赠侧唯一+捐赠侧同价才迁移，dry-run+CSV 审计后执行），532 件活跃持仓继承回 **¥652,704** 购入成本 / **Cost recovery**: 532 items inherited ¥652,704 via exact-wear zero-ambiguity matching
- **僵尸行源头根治**（提案5②）：租赁导入按 hash+磨损指纹复用 unknown 旧行（成本自然跟随），不再每个租赁周期建新行（此前每月净增 ~15k 死行） / Lease import reuses rows by wear fingerprint, ending per-cycle row creation
- **监控修真**（提案6②）：`/api/monitoring/status` 新鲜度阈值 60min→26h（采价为每日节奏，旧值导致永远 degraded）；`scheduler_jobs` 改实时读取 / Monitoring status fixed (26h threshold, live job list)

### 变更 / Changed
- **数据库与备份瘦身**（提案4/8）：`VACUUM` 489→140MB；归档清理 244,338 死行（item 字典 38.8k / item_avg_price 44.4k / 停用平台历史 140.8k / 旧告警 16.7k / 快照降采样 3.6k，先 `VACUUM INTO` 归档快照后删）→ 最终 **77MB**；`backup.sh` 改 `VACUUM INTO`+gzip（单份 468→**25MB**），完成首次**恢复演练**（integrity ok + 5 表行数一致）；清理 diag 临时 cron / DB & backups slimmed, 244k dead rows archived & pruned, restore drill done
- 红线遵守：`price_history` 202601 ALL-only 行原封未动（5,284 行）；合成数据修复确认 v0.9.3 已完成（ALL=分平台 MIN 聚合抽查通过） / 202601 ALL-row red line respected
- 新增索引 `lease_income_daily(name,date)`；`requirements-dev` 配合 CI / New index; dev deps for CI

## [0.12.0] - 2026-06-10

### 新增 / Added
- **首屏骨架屏**：统计卡/图表/Top20 网格在数据到达前显示 shimmer 占位（AURORA 叠加层实现），消除空白闪烁 / **Loading skeletons** for stat cards / charts / Top-20 grid before data arrives
- **数据自动保鲜**：页面可见时每 5 分钟静默刷新概览/图表；切回标签页若数据过期立即更新 / **Auto-fresh data**: silent 5-min refresh while visible; instant refresh when returning to a stale tab

### 修复 / Fixed
- **「偶尔刷新很慢」根因**：概览的悠悠估值缓存过期时改为 stale-while-revalidate——先返回现值、后台刷新，请求不再阻塞外部 API 1-3s；服务启动时预热缓存 / **Root cause of occasional slow refresh**: YouPin valuation caches now serve-stale-and-revalidate instead of blocking 1-3s at expiry; warmed at startup
- **估值解析漏网**：dashboard `_get_cached_steam_value` 未用 `parse_money`，带 ¥ 估值时抛错被吞（v0.9.3 修复未覆盖此处） / Valuation parse miss in dashboard (¥-prefixed values silently failed)
- **市价采集限速韧性**：SteamDT 4005 限速自动等窗重试一次；根因（双 worker 重复调度致 2 倍请求频率）已由 `--workers 1` 修复，本次补韧性 / collect_prices retries once after 4005 rate limit
- **DISTINCT ON 修复**：analysis 三处 `.distinct(col)` 在 SQLite 被静默忽略（已弃用语法），改为 `GROUP BY + MIN` 正确去重 / 3x DISTINCT-ON replaced with GROUP BY for SQLite correctness
- **弃用清理**：`datetime.utcfromtimestamp` → tz-aware；`Query(regex=)` → `pattern=` / Deprecation cleanups

### 变更 / Changed
- **聚合接口缓存**：`/api/analysis/overview`（原 ~0.6s）与 `/api/dashboard/chart-data`（原 ~0.2s）加 5 分钟 TTL 进程内缓存；compute-now / 标记已读 / 价格刷新后立即失效 / 5-min TTL caches on analysis overview & chart-data with proper invalidation
- **口径统一**：`/api/inventory` 逐件盈亏与 summary 估值从「仅 BUFF 价」改为「可得平台最低价」，与 dashboard 全站口径一致（新增 `current_price` 字段，`buff_value` 键名保留兼容） / Legacy inventory P&L now uses cheapest available platform price, consistent sitewide
- **索引**：`quant_signal(signal_date)`、`price_history(name, platform, record_date)` / New indexes

## [0.11.0] - 2026-06-10

### 新增 / Added
- **AURORA 设计系统**（`static/aurora.css`，纯叠加层，零业务 DOM 改动）：动态极光背景（GPU transform 漂移动画）+ SVG feTurbulence 胶片颗粒；oklch 广色域配色与 color-mix() 派生色；暗色「深空极光」/ 亮色「晨雾蓝瓷」双主题 / **AURORA design system** (`static/aurora.css`, pure overlay): living aurora background (GPU drift animation) + film grain; oklch wide-gamut palette with color-mix() derivations; dual dark/light themes
- **液态玻璃表面**：卡片家族（.card/.glass-chart/.glass-solid）统一镜面上缘高光、饱和玻璃模糊、悬浮浮起 + 极光描边；指针追光——光标处环境光斑（rAF 节流单监听） / **Liquid-glass surfaces**: specular top-edge highlight, saturated backdrop blur, hover lift + aurora ring; cursor-following ambient light (single rAF-throttled listener)
- **主题切换圆形揭幕**：View Transitions API 从按钮位置扩散揭幕，不支持的浏览器瞬时降级 / **Circular-reveal theme switching** via View Transitions API with graceful fallback
- **弹簧物理动效**：CSS `linear()` 真弹簧缓动（cubic-bezier 兜底）贯穿按钮按压/模态框入场/Tab 切换/卡片浮起 / **Spring-physics motion**: CSS `linear()` easing (cubic-bezier fallback) across buttons, modals, tabs, cards
- **细节打磨**：统计卡彩色顶缘光带 + 数值升格辉光、金融级 tabular-nums 等宽数字、品牌字极光渐变、玻璃化表头/分页/抽屉、focus-visible 焦点环、::selection 配色、text-wrap: balance / **Polish**: color-coded stat-card accents, tabular-nums digits, gradient brand text, glassed table headers/pagination/drawer, focus rings, selection colors

### 变更 / Changed
- 登录页重绘为同源 AURORA 语言（极光 + 玻璃卡 + 弹簧按钮） / Login page restyled with the same AURORA language
- `prefers-reduced-motion` 下全部动画/过渡/追光降级关闭 / All motion disabled under `prefers-reduced-motion`
- 悠悠 Token 过期横幅由刺红实色改为暗红玻璃 / Token-expiry banner softened from solid crimson to dark-rose glass

## [0.10.0] - 2026-06-10

### 新增 / Added
- **用户系统**：应用级账号登录（PBKDF2-SHA256 600k 迭代哈希 + HMAC 签名 HttpOnly session cookie，30 天有效），登录页 `/login`；`app_user` 表支持 super_admin/admin/viewer 角色 / **User system**: app-level account login (PBKDF2-SHA256 hashing + HMAC-signed HttpOnly session cookie, 30-day TTL), login page at `/login`, role column for future RBAC
- **密码管理**：右上角账户区修改密码（旧 session 全部失效）、退出登录；忘记密码可 SSH 运行 `scripts/create_user.py --reset` 重置 / **Password management**: in-app change password (invalidates old sessions) + logout; forgot-password recovery via `scripts/create_user.py --reset` over SSH
- **登录限速**：同 IP+用户名 5 次失败锁定 5 分钟，防爆破 / **Login throttling**: 5 failures per IP+username → 5-minute lockout
- 8 个新测试（哈希/token/中间件门禁/限速/改密失效/种子脚本），全量 332 通过 / 8 new tests, 332 total passing

### 变更 / Changed
- **取代 nginx Basic Auth**：单一登录入口，不再双重弹窗；未初始化用户时门禁直通（本地开发零配置） / **Replaces nginx Basic Auth**: single login, no double prompt; gate inactive until first user is seeded (zero-config local dev)
- **X-API-Key 仅保留给脚本/curl**：浏览器写操作走登录会话，0.9.2 的前端 API Key 弹窗注入已移除；`/api/auth/login|logout` 可匿名访问（凭证在 body 中验证） / **X-API-Key now scripts/curl-only**: browser writes ride the login session; the 0.9.2 frontend key-prompt was removed; `/api/auth/login|logout` are anonymous-accessible
- `/docs`、`/openapi.json` 等全部非白名单路径纳入登录门禁（此前公网可读） / `/docs`, `/openapi.json` and all non-whitelisted paths now require login (previously public)

## [0.9.3] - 2026-06-10

### 修复 / Fixed
- **估值解析崩溃致口径混用**：悠悠 API 估值带 `¥` 前缀时（如 `¥425194.14`）解析抛错，每日追踪静默 fallback 到 price_snapshot 最低跨平台价口径，与悠悠口径混用且无任何标记——抽出共享 `parse_money()`（剥 ¥/千分位/空白），tracker 与 collector 统一使用；fallback 发生时在 `daily_tracker.notes` 写入 `valuation_source=snapshot` 标记并告警 / **Valuation parse crash mixed methodologies**: '¥'-prefixed valuations crashed parsing, silently falling back to the price-snapshot methodology with no marker — extracted shared `parse_money()` used by both tracker and collector; fallback now writes a `valuation_source=snapshot` marker to notes
- **历史回填覆盖真实数据**：`POST /api/analysis/backfill` 的合成日线（均价插值 + 随机噪声）曾以 `on_conflict_do_update` 覆盖真实 ALL 聚合行——改为 `do_nothing`，合成数据只允许填补完全没有记录的日期 / **Backfill overwrote real history**: synthetic daily rows (avg interpolation + noise) overwrote real ALL aggregate rows via upsert — now `do_nothing`, synthetic data fills empty dates only
- **0 价占位行拖垮 ALL 聚合**：停用平台/抓取失败写入的 0 价行被 `MIN` 聚合纳入，导致历史上 ~20% 的 ALL 日线为 0（窗口前 30 天高达 64%）——日聚合与 ALL 行生成均加 `> 0` 过滤，0 价快照不再产生平台行 / **Zero-price placeholder rows dragged ALL aggregates to 0** (~20% of ALL rows historically): daily aggregation and ALL-row generation now filter `> 0`; zero-price snapshots no longer produce platform rows

### 新增 / Added
- `scripts/restore_all_rows.py`：重放 aggregate_daily 的跨平台聚合逻辑，恢复 2026-06-08 回填事故覆盖的 45 天 ALL 行；无源可恢复的纯合成行删除；默认 dry-run / restore script replaying the cross-platform aggregation to recover the 45 days of ALL rows overwritten by the 2026-06-08 backfill; pure-synthetic rows with no source are deleted; dry-run by default
- 14 个新测试（parse_money 特征用例 / fallback 标记 / backfill 防覆盖 / 恢复脚本），全量 323 通过 / 14 new tests, 323 total passing

## [0.9.2] - 2026-06-10

### 新增 / Added
- **写操作 API Key 鉴权**：服务端配置 `APP_API_KEY` 后，所有 `/api/` 写请求（改价、上架、下架、导入、SMS 登录等）必须携带密钥；在原 `Authorization: Bearer` 之外新增 `X-API-Key` 头支持，以兼容 nginx Basic Auth 占用 Authorization 头的部署 / **API-key auth for write operations**: with `APP_API_KEY` set, all `/api/` mutating requests require the key; added `X-API-Key` header support (besides `Authorization: Bearer`) to coexist with nginx Basic Auth
- **前端自动附带密钥**：首次写操作收到 401 时弹窗输入一次，存入 localStorage 后自动注入后续请求 / **Frontend auto-attach**: prompted once on first 401, key stored in localStorage and injected into subsequent writes
- CORS 允许方法补充 `PUT`（改价端点），允许头补充 `X-API-Key` / CORS: added `PUT` method and `X-API-Key` header to allowlists

## [0.9.1] - 2026-06-08

### 修复 / Fixed
- **桌面端图表 resize 崩溃**：窗口缩放 / 打开 DevTools 时概览图表变空白且无法恢复——移除 fingerprint 中的容器宽度,避免 ResizeObserver 与 Chart.js 原生 `responsive` 双重重建导致 `getContext` 报错 / **Desktop chart resize crash**: charts blanked on window resize / DevTools — removed container width from fingerprint to stop ResizeObserver double-rebuild racing Chart.js's native `responsive` (getContext null)
- **iOS WebKit 概览图表空白**：iOS 会丢弃视口外 canvas 的后备存储,导致首屏折叠下方的持仓构成 / 盈亏排名 / 盈亏率分布绘制后空白、滚动到可见也不恢复——改为 IntersectionObserver 在图表滚入视口时强制 `chart.render()` 重绘(桌面 / DevTools 手机模式均为 Chromium 引擎,复现不出此 WebKit 专有问题) / **iOS WebKit blank overview charts**: iOS drops the backing store of off-screen canvases — force `chart.render()` on scroll-into-view via IntersectionObserver (WebKit-only; not reproducible on Chromium desktop/DevTools)

## [0.9.0] - 2026-06-08

### 新增 / Added
- **概览数据可视化升级**：持仓构成环形图（按类型市值）、盈亏 Top 涨/跌排行、盈亏率分布柱图、持仓价值 Top20 图标网格 / **Overview data-viz upgrade**: type-composition doughnut, P&L gainers/losers ranking, P&L-rate distribution, Top-20 holdings icon grid
- **只读聚合接口** `/api/dashboard/chart-data`：按 `market_hash_name`/`item_type` 聚合，为新图表供数（不改任何业务计算） / **Read-only aggregation endpoint** `/api/dashboard/chart-data` feeding the new charts
- **移动端顶栏「更多」抽屉 + 横向滚动 Tab 栏**：主操作（同步库存）常驻可见，其余操作收进抽屉 / **Mobile header "More" drawer + horizontal-scroll tab bar**: primary Sync stays visible, secondary actions in drawer
- **移动端持仓列表卡片化**：每行 → 纵向卡片（饰品/状态/市价/盈亏），点击复用详情侧栏；收益追踪表 sticky 左固定首列 / **Mobile holdings card list** (taps reuse detail panel); tracker table sticky left column

### 修复 / Fixed
- **图表渲染根因修复**：宽度为 0 时不再渲染/缓存，切换到隐藏 Tab 再切回不再永久空白；统一 IntersectionObserver/ResizeObserver 生命周期 / **Chart lifecycle root-cause fix**: never render/cache at width 0; switching to a hidden tab and back no longer blanks; unified IO/RO lifecycle
- **图表 resize 崩溃修复**：移除 fingerprint 中的宽度，避免与 Chart.js 原生 `responsive` 双重重建导致 `getContext` 报错与图表清空 / **Resize-crash fix**: removed width from fingerprint to stop double-rebuild racing Chart.js's native responsive (getContext null / blank charts)
- **消除移动端页面级横向溢出**：顶栏、详情侧栏 `min(100vw,380px)`、宽表父链 `min-width:0` / **Eliminated page-level horizontal overflow on mobile**: header, side panel `min(100vw,380px)`, wide-table parent chains `min-width:0`

### 变更 / Changed
- 概览 6 张统计卡精简为 4 张信息密度更高的玻璃卡；大数字显示完整精确值，hover 显示精确数据 / Overview stat cards consolidated 6→4 denser glass cards; full precise big numbers with hover detail
- 图表跟随三态主题（light/dark/system）；ApexCharts 收益/价格图主题色不再写死 / Charts follow light/dark/system theme; ApexCharts tracker/price colors no longer hardcoded
- 移动端收尾：正文/数字 ≥12px、主操作点击高度 ≥40px、隐藏次要时间戳、模态 `max-height:90vh` 可滚动、表格移动端整页滚动 / Mobile polish: body ≥12px, tap targets ≥40px, hidden secondary timestamps, scrollable modals, page-scroll tables
- 纯呈现层改造，未改动任何数据计算/聚合/API/业务逻辑 / Presentation-layer only; no changes to data aggregation/API/business logic

## [0.8.0] - 2026-06-08

### 新增 / Added
- **悠悠有品交易记录导入工具**（`scripts/import_youpin.py`）：5 级智能匹配（commodity_id → asset_id → hash+磨损 → hash_name → 中文名），FIFO 多实例绑定，支持 API/CSV/JSON 数据源，`--dry-run`/`--overwrite` / **YouPin trade record import tool**: 5-level smart matching with FIFO binding, API/CSV/JSON sources, dry-run & overwrite modes
- **手动成本录入 CLI**（`scripts/manage_cost.py`）：list/set/set-id/batch/stats 命令，Rich 表格展示，支持按名称/ID/批量设置购入价 / **Manual cost entry CLI**: list/set/set-id/batch/stats commands with Rich tables
- **利润监控终端仪表盘**（`scripts/dashboard.py`）：持仓总览、PnL 排行、信号高亮（$$>100%, $>50%, !!<-20%），`--watch` 持续刷新 / **Profit monitoring CLI dashboard**: portfolio overview, PnL ranking, signal highlights, --watch mode
- **YAML 告警规则外置**（`config/alert_rules.yaml`）：7 条全局规则 + 按类目阈值覆盖（刀/手套利润止盈线 60%/120%，贴纸 30%），mtime 缓存热加载 / **YAML alert rules**: 7 global rules + per-category threshold overrides, mtime-based hot reload
- **库存/租赁同步诊断日志**：每次同步后输出 API 聚合值 vs 实际遍历值对比（件数/价值/日租 DIFF） / **Sync diagnostic logging**: API aggregate vs actual traversal comparison after each sync

### 修复 / Fixed
- **租赁分页不再依赖 totalCount**：API 的 totalCount 可能缓存偏小导致漏拉最后一页，改为循环到空页为止（与库存同策略） / **Lease pagination fix**: no longer relies on API's potentially stale totalCount, loops until empty page

### 变更 / Changed
- Phase 1 降频优化：采价间隔 30min→2h，快照 15min→1h，缓存 TTL 扩展至 30min / Phase 1 tuning: price collection 30min→2h, snapshots 15min→1h, cache TTL 30min
- 新增 `rich`、`pyyaml` 依赖 / Added `rich`, `pyyaml` dependencies
- 量化引擎告警从硬编码改为 YAML 驱动 / Quant engine alerts switched from hardcoded to YAML-driven

## [0.7.0] - 2026-05-29

### 新增 / Added
- **挂售快照功能**：保存货架数据供下架后参考 / **Listing snapshot**: save shelf data for reference after delisting
- **加仓/减仓快捷操作**：收益追踪成本基准调整 / **Position sizing shortcuts**: adjust cost basis for income tracking
- **概览走势图双大类切换**：组合价值 + 租赁走势 / **Overview chart dual-category toggle**: portfolio value + rental trends
- **月度汇总缺失天数预估** + 日报表全列可编辑 / **Monthly summary missing-day estimation** + editable daily report columns

### 修复 / Fixed
- **多 worker 环境下 token 同步**：修复导入 84101 错误 / **Multi-worker token sync**: fixed import 84101 error
- **Chart.js resize 无限递归**导致图表消失 / **Chart.js resize infinite recursion** causing charts to vanish
- **快照保存**处理空字符串字段转换 / **Snapshot save** handles empty string field conversion
- **库存市值计算统一**为悠悠 API 估值，消除 SteamDT 定价偏差 / **Unified market value** to use YouPin API valuation

### 变更 / Changed
- **首页改为资产概览+持仓列表合并**，收益追踪移至第二 Tab / **Homepage merged** overview + holdings, income tracker to 2nd tab
- **概览走势图从 ApexCharts 迁回 Chart.js 4.4.0**（稳定性更好） / **Overview charts** migrated back from ApexCharts to Chart.js 4.4.0 (stability)
- **全面性能优化**：持久 HTTP 客户端、N+1 查询修复（spread_radar 批量查询 + 信号计算预加载）、JS 代码分割、Pydantic 请求模型 / **Performance overhaul**: persistent HTTP client, N+1 query fixes, JS code splitting, Pydantic models
- **安全加固**：CORS 收紧、SQL 参数化补全 / **Security hardening**: CORS tightening, SQL parameterization
- Tracker 表格默认只渲染 30 行，减少 Alpine 绑定数 5600→1200 / Tracker table renders 30 rows by default, reducing Alpine bindings 5600→1200
- 定时任务改为 PDT 时区 / Scheduled tasks switched to PDT timezone

## [0.6.0] - 2026-03-21

### 新增 / Added
- **每日收益追踪系统**：替代 Excel 手动记录，自动抓取出租件数、总价值、日租金、年化收益率、库存价值、涨跌 / **Daily Income Tracker**: Replaces manual Excel tracking with auto-capture of rental count, value, daily income, annualized returns, inventory value, price change
- **自动快照**：每日 00:01 UTC 从悠悠 API 获取租赁统计 + DB 查库存，几秒完成 / **Auto snapshot**: Daily 00:01 UTC, fetches rental stats from Youpin API + DB inventory query in seconds
- **月度汇总**：自动聚合总收入、服务费(20%)、净租金、净租金年化 / **Monthly summary**: Auto-aggregated income, service fee (20%), net rental, annualized net rental
- **Excel 导入/导出**：支持 xlsx 格式上传导入和下载导出 / **Excel import/export**: Upload xlsx to import, download to export
- **前端「收益追踪」Tab**：汇总卡片、趋势图表（综合年化/日租金/库存价值/涨跌）、月度汇总表、每日明细表格 / **Frontend "Income Tracker" tab**: Summary cards, trend charts, monthly summary table, daily detail table
- **历史数据导入**：从 csgo饰品收益.xlsx 导入 123 条建仓后数据（2025-10 至 2026-03） / **Historical data import**: 123 records imported from Excel (Oct 2025 - Mar 2026)

### 变更 / Changed
- 版本号升至 v0.6.0 / Version bump to v0.6.0
- 定时任务增至 7 个 / Scheduled jobs increased to 7
- 新增 `openpyxl` 依赖 / Added `openpyxl` dependency

## [0.5.2] - 2026-03-21

### 修复 / Fixed
- **购买记录匹配失败**：修复 `assertId` 拼写错误（应为 `assetId`），导致 asset_id 匹配分支永远无法命中 / **Buy record matching broken**: Fixed `assertId` typo (should be `assetId`), causing asset_id matching branch to never trigger
- **物品"消失"bug**：对账逻辑将物品设为 `status="unknown"` 但该状态不在合法集合中，导致 UI 不可见。已将 `unknown` 加入 `VALID_STATUSES`，前端新增「待确认」过滤选项 / **Items "disappearing"**: Reconciliation set `status="unknown"` which wasn't in `VALID_STATUSES`, making items invisible. Added `unknown` to valid set with "Unknown" filter option
- **市价刷新状态卡死**：`bulk_refresh_market_prices` 异常后状态永久卡在 `running`，已添加 `finally` 防护 / **Market refresh state stuck**: Added `finally` guard to prevent `market_refresh_state` from being permanently stuck as "running"
- **前端静默错误**：修复 22 个空 `catch {}` 块，补充用户可见的错误提示 / **Silent frontend errors**: Fixed 22 empty `catch {}` blocks with proper toast error messages
- **轮询计时器竞态条件**：快速连续点击可创建重复 `setInterval`，已添加 `clearInterval` 防护 / **Polling timer race condition**: Rapid clicks could create duplicate intervals, added `clearInterval` guard
- **浮点定价精度**：`calc_sell_price` 改用 `Decimal` 精确运算，消除 0.01 级别误差 / **Float pricing precision**: `calc_sell_price` now uses `Decimal` to eliminate penny-level rounding errors
- **磨损值匹配过严**：`import_buy_records` 中磨损值比较容差从 `1e-8` 放宽到 `0.0001` / **Wear value matching too strict**: Tolerance in `import_buy_records` relaxed from `1e-8` to `0.0001`
- **表单缺少输入验证**：`saveReprice` 和 `smartListItem` 提交前验证数值有效性 / **Missing form validation**: Added numeric validation before submit in `saveReprice` and `smartListItem`

### 变更 / Changed
- **CORS 收紧**：`allow_origins` 从 `*` 限制为实际部署域名和 localhost / **CORS tightened**: `allow_origins` restricted from `*` to actual deployment domains
- **Token 持久化安全加固**：改为原子写入（tmp + replace）+ `chmod 600` / **Token persistence hardened**: Atomic writes (tmp + replace) with `chmod 600`
- **并发保护**：市价刷新和价格采集添加 `asyncio.Lock`，防止定时任务与手动操作冲突 / **Concurrency protection**: Added `asyncio.Lock` to market refresh and price collection, preventing scheduler/manual conflicts
- **调度任务错开执行**：价格采集在 :00/:30，组合快照在 :15/:45，添加 `max_instances=1` / **Staggered scheduler**: Price collection at :00/:30, portfolio snapshot at :15/:45, with `max_instances=1`
- **数据库迁移日志**：新增列成功时记录日志，不再完全静默 / **Migration logging**: Successful column additions now logged
- **图片加载失败统一处理**：使用 placeholder SVG 替代隐藏元素 / **Unified image error handling**: Placeholder SVG instead of hiding elements

### 新增 / Added
- **定价算法单元测试**：19 个测试覆盖 `calc_sell_price` / `calc_lease_price` 核心场景（outlier 过滤、止盈率、浮点精度、租赁定价） / **Pricing algorithm unit tests**: 19 tests covering `calc_sell_price` / `calc_lease_price` core scenarios (outlier filtering, take-profit, float precision, lease pricing)

## [0.5.1] - 2026-02-26

### 修复 / Fixed
- **ATH 数据不准确**：新增 CSQAQ API ATH 字段探测，优先使用 API 长期历史数据（覆盖3年+），本地 45 天数据仅作兜底 / **Inaccurate ATH**: Added CSQAQ API ATH field detection, prefer API long-term historical data (3yr+ coverage), local 45-day data as fallback only
- **资产概览市值不刷新**：导入同步完成后自动调用 `loadAll()` 刷新所有数据 / **Market value not refreshing**: Auto-call `loadAll()` after import sync completes
- **组合走势图曲线显隐按钮无效**：使用 Chart.js 标准 `setDatasetVisibility()` API 替代直接设置 `dataset.hidden` / **Chart toggle buttons broken**: Use Chart.js standard `setDatasetVisibility()` API instead of directly setting `dataset.hidden`

### 变更 / Changed
- **年化收益拆分为盈亏率 + 含租预期收益率**：原 CAGR 年化收益替换为「盈亏率」(市价-成本)/成本 和「含租预期收益率」假设价格不变收一年租金后的总回报率 / **Split annual return into P&L Rate + Projected Return**: Replaced CAGR annualized return with "P&L Rate" (market-cost)/cost and "Projected Return" assuming flat price + 1 year rental income
- **新增悠悠大会员开关**：前端 localStorage 持久化，开启后租金年化按 310 天计算，关闭按 188 天 / **Added Youpin VIP membership toggle**: localStorage persistent, 310 days when enabled vs 188 days default
- 数据库自动补齐 3 个新字段：`pnl_rate`、`projected_annual_return`、`csqaq_ath_price` / DB auto-migration adds 3 new columns

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
