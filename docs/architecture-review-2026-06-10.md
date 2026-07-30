# CS2 Inventory Manager — 架构审查与改进提案

**日期**: 2026-06-10 · **范围**: 全代码库 + 生产库只读查询 + journalctl + nginx 配置 + Steam API 只读探针
**约定**: [事实] = 代码/数据/日志直接证实;[假设] = 推断,附验证方法。
**度量纪律**: market_value(悠悠 API 聚合)与 PnL(price_snapshot 逐件 vs 成本)全程分开表述,未混用。

---

## 一、系统现状图

### 数据流

```
SteamDT batch API ──(每日 00:05 PDT, 267品/3批)──→ price_snapshot ──(00:12 聚合)──→ price_history(OHLC)
CSQAQ API ──(每日 00:02, 244品)──→ quant_signal(daily_rent/rental_annual/存世量) + inventory_item 元数据补全
悠悠有品 API ──(手动 import/quick + 每日 tracker)──→ inventory_item(stock→in_steam, lease→rented_out)
                                              └──→ daily_tracker(租金/估值/年化) + portfolio_snapshot
Steam Community API ──(自 2/21 后无成功同步痕迹, 见提案6)──→ inventory_item + storage_unit
前端: 单页 index.html(2808行) + app.js(2369行), Alpine.js + Chart.js + ApexCharts 双图表库
```

### 定时任务链(美西时区, main.py:88-104)

| 时刻(PDT) | 任务 | 状态 |
|---|---|---|
| 00:00 | snapshot_daily(daily_tracker) | 运行中,**双跑** |
| 00:02 | csqaq_daily_sync | 运行中,**双跑互相 429** |
| 00:05 | collect_prices(SteamDT) | 运行中,**双跑互相限速** |
| 00:12 | aggregate_daily(OHLC) | 运行中,双跑(幂等) |
| 00:15 | snapshot_portfolio | 运行中,双跑(幂等) |
| 01:00 | cleanup_old_snapshots(keep 3d) | 运行中,双跑(幂等) |
| — | compute_signals | 已禁用(仅手动 compute-now) |

cron(root): monitor.sh 每 5 分钟、backup.sh 每 6 小时、diag_rss.sh 每 30 分钟(临时诊断)。

### 数据库画像(生产, 2026-06-10 实测)

| 表 | 行数 | 备注 |
|---|---|---|
| inventory_item | 53,811 | **unknown 49,475 (92%)**;活跃仅 4,327(in_steam 426 + rented_out 3,901);sold 9 |
| price_history | 258,023 | ~73k 行/月增长;含 7 个停用平台 ~160k 行;ALL 行近 45 天被合成数据污染(提案7) |
| item_avg_price | 44,381 | backfill 时代遗留 |
| item | 39,154 | SteamDT 全量目录,实际仅 ~600 个名字被引用 |
| quant_alert | 34,628 | **未读 34,595 / 已读 33** |
| quant_signal | 25,554 | CSQAQ 同步仍每日 +221 行 |
| portfolio_snapshot | 4,899 | 30 分钟时代遗留 + 现每日 1-2 条 |
| price_snapshot | 2,737 | 3 天保留生效 ✓ |
| daily_tracker | 201 | 核心产出表,近 30 天无缺日 ✓ |
| 其余 | storage_unit 9 / listing_snapshot 1(+items 133) / tracker_config 0 | |

注: ORM 定义 13 张表,生产实际 13 张业务表;任务背景中"9 张表"与实际不符。

### 磁盘/内存画像

- [事实] DB 文件 489 MB,`page_count=119,576 / freelist_count=85,007` → **71% 是空闲页**,真实数据 ≈ 141 MB。从未 VACUUM。
- [事实] 备份 30 份 × 489 MB ≈ **12.3 GB**(全盘 23 GB 用量的一半以上)。sqlite `.backup` 原样复制空闲页。
- [事实] **RSS 诊断可结案**: diag_rss.log 双 worker 各 ~105/110 MB,数小时纹丝不动,无泄漏。Stage 2 等的 RSS 数据已到位,可以删 diag_rss.sh cron。
- [事实] 内存 7.9 GB 余量充足;磁盘 24%,不紧急但备份占比畸高。

### 外部依赖

| 依赖 | 用途 | 失效行为 |
|---|---|---|
| 悠悠有品 API(token,SMS 登录) | 估值/租赁/导入/上架操作 | 静默 fallback 到 price_snapshot 口径(无告警,见提案3) |
| SteamDT API(key) | 每日采价 | 批次失败仅 warning,当日缺数 |
| CSQAQ API(key) | 租金/存世量 | 429 时该品当日缺数 |
| Steam cookie(2/26 配置) | 原生库存同步 | [假设] 已过期,同步链路实际死亡(提案6) |
| jsdelivr/cloudflare CDN | 前端三个库 | 断网时页面瘫 |

---

## 二、悬案结论:Storage Unit

**问题**: 非可交易清单中的 Storage Unit 是否包含被排除在总资产之外的可交易库存?

**结论**: "排除机制"已证实存在且必然;**柜内是否真的有物,所有可用 API 均无法判定**,需一次性人工验证。

证据链:

1. [事实] 非可交易清单里的 9 个 "Storage Unit"(inventory_item id 3520-3532)来自**悠悠 stock 导入路径**(class_id=STEAM_PROTECTED),其 `tradable=False` 是 import_stock_records 对所有导入行的**硬编码**(youpin.py:977),不反映物品真实属性——"非可交易"标签对悠悠导入物品全部失真。
2. [事实] storage_unit 表记录 9 个储物柜容器,**全部 last_synced_at 停在 2026-02-21 14:14** → Steam 原生同步自 2/21 后无成功运行痕迹(或运行了但储物柜不可见,代码 `_sync_storage_units` 在 current_units 为空时直接 return,不会更新行)。数量 9 与悠悠清单中的 9 个一致。
3. [事实] 今日用 .env cookie 直连 Steam API 探针: `total_inventory_count=44`,可见 31 件全为不可交易纪念品(Extraordinary Collectible×30 + Music Kit×1),**0 个储物柜可见**,13 件不可见。
   [假设] Steam cookie(2/26 写入)已过期,探针看到的是公开视图,13 件不可见物可能含 9 个储物柜。验证: 重新抓 cookie 后再跑一次同样的只读探针。
4. [事实] 储物柜**内容物**对系统全部数据源(Steam top-level API、悠悠 stock/lease)不可见;`in_storage` 状态当前 0 行,存取推断逻辑从未实际触发过。
5. [事实] 因此:若柜内有可交易饰品,它们**必然**被同时排除在 market_value(悠悠口径)、PnL(snapshot 口径)、件数统计三者之外。
6. [假设·间接信号] cost_basis 4.4M vs daily_tracker inventory_value 3.88M 的缺口,既可能是市价下跌(PnL 口径同期 -707k,量级吻合),也可能部分在柜中——两者无法从数据上区分。

**建议动作**(一次性,非 /goal): 打开 CS2 客户端清点 9 个储物柜。若有值钱物,加一张手工登记表(casket_id, 物品, 估值)即可,不值得做自动化(Valve 无 API)。

---

## 三、改进提案(按 影响/成本 排序)

### 提案 1 — 安全:全站零鉴权,真实资金操作端点公网裸奔 ⚠️

**问题** [事实]:
- 生产 .env **没有 APP_API_KEY** → APIKeyMiddleware(main.py:44)整体直通;所有 GET 本来就不设防(中间件设计如此)。
- nginx 无任何 auth / IP 限制 / 速率限制,`cs2.kingke.dev` 走 certbot → **证书透明度日志使域名公开可发现**。
- access.log 实测:腾讯云 IP 段(43.x/129.226.x)及测绘机器人已在抓首页并拿到 200(完整 dashboard HTML)。
- 公网可达的写端点包括:`POST /api/listing/sell|lease|both`、`PUT /reprice`、`POST /batch-smart-reprice`、`POST /batch-delist`(**直接操作悠悠货架的真实资金动作**);`POST /api/youpin/auth/send-sms`(对任意手机号发短信,滥用向量);`POST /api/youpin/auth/apply-token`(可被注入攻击者 token)。
- 公网可读的 GET 包括总资产 ¥3.9M、全部持仓明细、悠悠昵称——隐私与社工素材。

**方案**: nginx 层加 Basic Auth(或 IP allowlist)整站兜底 + 同时设置 APP_API_KEY 作纵深防御;`/health` 留白名单给 monitor.sh。前端需带凭证,Basic Auth 对单用户场景零代码改动。
**工作量**: S(半天) · **风险**: 低(配置回滚即恢复) · **/goal 适配**: 适合。完成条件:外网匿名 curl 首页/API 返回 401;monitor.sh 健康检查仍绿;用户浏览器可正常使用。

### 提案 2 — 可靠性:workers=2 导致全部定时任务双跑、外部 API 自相残杀

**问题** [事实]:
- systemd `--workers 2`,每个 worker 各起一套 APScheduler。journal 实锤:两个 PID(128674/128675)同秒各跑一遍所有任务。
- 直接后果(6/9 实测):collect_prices 两实例互相触发 SteamDT 限速,一个 worker 3 批中**2 批失败**(100/267 品),另一个 1 批失败(167/267)→ 每天 price_snapshot 覆盖不全靠运气,直接抖动 PnL 口径。
- csqaq_daily_sync 双跑互相 429:`133 synced, 111 errors` / `160 synced, 84 errors` → **每天 ~40% 的租金数据(daily_rent/rental_annual,租赁监控的核心输入)拿不到**。
- 内存态(_overview_cache、market_refresh_state、_import_state、collector_state)各 worker 独立 → 前端轮询进度会"闪烁",/api/monitoring/status 的 collector 状态只反映命中的那个 worker。

**方案**: 改 `--workers 1`。该应用 QPS 极低(单用户),单 worker 绰绰有余;一次改动同时治好:SteamDT 批次失败、CSQAQ 缺数、状态闪烁、双倍外部 API 消耗。(备选:保留 2 worker、用文件锁让 scheduler 单实例——复杂度不值得。)
**工作量**: S(一行 + 验证) · **风险**: 低 · **/goal 适配**: 适合。完成条件:次日 journal 中每个任务 START 只出现一次;collect_prices DONE=267/267;csqaq errors < 10%。

### 提案 3 — 数据质量:估值解析 bug 致 daily_tracker 静默混用两套度量体系

**问题** [事实]:
- journal 实锤:`tracker snapshot_daily: 获取库存估值失败: could not convert string to float: '¥425194.14'`。
- 根因:tracker.py:150 `float(str(stock_valuation).replace(",", ""))` **没剥 '¥' 前缀**;collector.py:475 同逻辑却有 `.replace("¥","")`——同一解析写了两遍且不一致。
- 失败时静默 fallback 到 price_snapshot 最低跨平台价×件数 → `daily_tracker.inventory_value` 一天是悠悠口径、一天是 snapshot 口径,**正是任务要求"不得混用"的两套度量体系,且无任何标记可区分哪天是哪种**。6/9 实测:00:00 定时跑成功(悠悠口径 3,857,749),用户手动 08:21 触发失败走 fallback(snapshot 口径 3,882,395)并覆盖了当日记录。
- [假设] '¥' 前缀是悠悠 API 不稳定返回(有时带有时不带),验证:连续几天记录原始 valuation 字符串。

**方案**: 抽一个 `_parse_money()` 共享 helper(剥 ¥/,/空白),tracker 与 collector 共用;fallback 发生时在 daily_tracker.notes 写入 `valuation_source=snapshot` 标记;补 characterization 测试钉死('¥1,234.56'、'1234.56'、''、None 四个 case)。
**工作量**: S · **风险**: 低 · **/goal 适配**: 适合。完成条件:pytest 新增用例通过;连续 3 天 journal 无该 warning 或 fallback 有标记。

### 提案 4 — 磁盘:VACUUM + 备份瘦身(Stage 2 的核心,RSS 前提已满足)

**问题** [事实]: DB 71% 空闲页(489 MB 实际 141 MB);备份 12.3 GB;backup.sh 复制空闲页。RSS 诊断已确认无内存泄漏,Stage 2 的前提条件解除。

**方案**(顺序执行):
1. 低峰期 `VACUUM`(141 MB 重写,秒级~分钟级;事先 .backup 一份);
2. backup.sh 改 `sqlite3 "$DB" "VACUUM INTO '$BACKUP_FILE'"` 或备份后 gzip(SQLite 高压缩,预计单份 30-50 MB,30 份 ≈ 1.5 GB);
3. **做一次恢复演练**(从未做过):取最新备份在 /tmp 起只读实例,验证 `PRAGMA integrity_check` + 关键表行数 + /api/tracker/daily 可读——备份没演练过恢复等于没有备份;
4. 删 diag_rss.sh cron(诊断已结案)。
**工作量**: S-M · **风险**: 中(VACUUM 期间写锁,需停服或选在 01:30-07:00 无任务窗口) · **/goal 适配**: 适合。完成条件:DB < 200 MB;单份备份 < 60 MB;恢复演练文档化。

### 提案 5 — 数据质量:92% 僵尸行 + ¥30.7M 成本挂在死行上,PnL 覆盖率仅 51%

**问题** [事实]:
- unknown 状态 49,475 行(YOUPIN 42,938 + STEAM_PROTECTED 6,489),每月净增 ~15k 行,无任何清理路径;`unknown` 甚至不在 db_models 文档的状态机里。
- 机制(代码证实):import_lease_records 每轮把 rented_out 全量重置为 unknown(youpin.py:1079-1086),按 commodity_id 回写;**同一件物理饰品每个租赁周期生成新 commodity_id → 新行**,旧行连同其 purchase_price 永久滞留。
- 后果:23,516 个 unknown 行携带共 **¥30.7M** 的购入成本;活跃 4,327 件中仅 2,224 件有成本(51.4%)→ **PnL 只覆盖一半持仓**。
- [事实] 实测 752 个无成本活跃行可通过 (market_hash_name, abrade) 与有成本 unknown 行精确配对 → 成本覆盖率可提升至 ~68.8%。

**方案**(分两步):
1. **成本继承迁移**(脚本,先 dry-run 输出 CSV 供人工抽查):同 hash+abrade 唯一匹配时,把 unknown 行成本转移到活跃行;
2. **身份匹配改造**:abrade(磨损值)是物理指纹,import_lease_records 改为先按 hash+abrade 找旧行复用,而非无脑建新行;unknown 中无成本且 >90 天的行归档后删除。
**工作量**: M(2-3 天,核心风险在匹配歧义:同 hash 同磨损多件时不可自动迁移) · **风险**: 中-高(动持仓数据;必须备份 + dry-run + 测试) · **/goal 适配**: 适合但要拆两个 goal,完成条件:活跃成本覆盖率 ≥65%;dry-run 报告人工确认后才执行;pytest 全绿。

### 提案 6 — 可靠性:Steam 原生同步链路已死(cookie 过期),无人知晓

**问题**:
- [事实] storage_unit.last_synced_at 全停在 2/21;steam_native 活跃行 0;探针只见公开物品。
- [假设] Steam cookie(2/26 写入 .env)已过期 → POST /api/inventory/sync 实际已不可用或只看到公开子集。验证:重抓 cookie 跑探针对比可见数。
- 推广:悠悠 token 同样会过期(code=84101),目前失效时各调用方静默 fallback(估值 0 → 缓存兜底),**用户可能数天后才从图表异常发现数据停更**。
- [事实] /api/monitoring/status 永远 "degraded"(60 分钟新鲜度阈值 vs 每日采集节奏),scheduler_jobs 列表还是硬编码的"30 min"旧文案——状态页已失去告警价值,monitor.sh 也只查 /health 不查数据新鲜度。

**方案**: ① 凭证哨兵:每日任务链头部加 check_token_status + Steam cookie 探测,失效时通过邮件/Server酱/Telegram 主动推送(系统当前完全没有外发告警通道);② /status 新鲜度阈值改 26h、scheduler_jobs 改为 `scheduler.get_jobs()` 动态生成;③ monitor.sh 增查 data-freshness。
**工作量**: S-M · **风险**: 低 · **/goal 适配**: 适合。完成条件:人为改坏 token 后 24h 内收到通知;/status 在正常日返回 healthy。

### 提案 7 — 数据质量:backfill 合成数据已污染 price_history 真实历史

**问题** [事实]:
- collector.backfill_avg_prices(collector.py:347-385)用 7/30/90 天均价插值 + **±1.5% 随机噪声**生成"看起来真实"的 45 天 ALL 平台日线,`on_conflict_do_update` 直接**覆盖真实聚合行**,无任何标记。
- 用户于 6/8 09:38 触发过 `POST /api/analysis/backfill`(access log 实锤,双 worker 各跑一次)→ price_history ALL 行近 45 天(约 4/24-6/7)现为合成数据,走势图展示的是假历史。

**方案**: ① ALL 行可恢复——分平台(BUFF/YOUPIN/STEAM)真实行还在,重放 aggregate_daily 的 ALL 聚合逻辑覆盖回去;② backfill 端点要么下线、要么改为只填"无任何数据的日期"且写入 synthetic 标记列;③ 量化代码保留作 showcase 不受影响。
**工作量**: S-M · **风险**: 低(恢复脚本本身幂等) · **/goal 适配**: 适合。完成条件:抽查若干品种 ALL 行 = 对应日期分平台行的 MIN 聚合;backfill 不再能覆盖真实行。

### 提案 8 — 死数据归档(Stage 2 收尾)

**问题** [事实]: item 表 39k 行只用 ~600;item_avg_price 44k 行无活跃写入路径;price_history 7 个停用平台 ~160k 行;quant_alert 34.6k 行 99.9% 未读(告警系统实际无人消费);portfolio_snapshot 4.9k 行多为 30 分钟时代高频数据;listing_snapshot 功能几乎未被使用(1 条)。

**方案**: 归档导出(SQL dump 进 archive/ 或单独 sqlite 文件)→ DELETE → 并入提案 4 的 VACUUM。quant_signal/quant_engine **代码**保留(用户已决定作 portfolio showcase),只清数据。portfolio_snapshot 高频旧数据可降采样为日粒度。
**工作量**: M · **风险**: 中(删数据,依赖提案 4 的备份+演练先行) · **/goal 适配**: 适合,完成条件:DB 数据页 < 60 MB;前端各图表无回归;归档文件可独立打开。

### 提案 9 — 产品价值:租赁监控工具最缺的两个能力

**a. 单品租赁实绩归因**(最有价值的缺失能力)
[事实] daily_tracker 只有账户级总收入(¥2,814/天);lease 记录里每单的 shortLeasePrice/commodity_id 在导入时已经过手却全部丢弃,只更新状态。
→ 新表 lease_income_daily(commodity_id, date, rent),import 时顺手落库,即可回答:**每件饰品的实际出租率、实际年化、该卖谁该续谁**——这是"持仓/租赁监控工具"的核心问题,现在只能靠 CSQAQ 的市场租金(还缺 40%)。
**工作量**: M · **/goal 适配**: 适合。完成条件:前端单品页显示近 30 天实际租金曲线 + 实际年化排行。

**b. 凭证失效主动告警** — 已并入提案 6①。

### 提案 10 — 测试:最值得先补的核心路径

结合已有 301 用例(覆盖率 42%),边际价值最高的三块:
1. `_parse_money` / valuation 解析(钉提案 3 的 bug,'¥'/逗号/空串/None);
2. import_lease_records 的 unknown 重置-回写-归还循环(钉提案 5 的机制,现有 youpin 测试只覆盖分页和解析);
3. 提案 5 成本迁移脚本的 dry-run 输出(唯一匹配/歧义/无匹配三分支)。
**工作量**: S(随各提案捆绑交付,不单列)

---

## 四、Top 3 优先级

| # | 提案 | 理由 |
|---|---|---|
| **1** | 提案 1(安全加锁) | 唯一可能造成**真实资金损失**的项:改价/上架/下架端点公网无鉴权,扫描器已在门口,域名因 CT 日志必然可发现。半天工作量,影响/成本比无可匹敌。 |
| **2** | 提案 2(workers=1) | 根因级修复:一行改动同时治好每日采价缺数、CSQAQ 40% 租金数据丢失、状态闪烁、双倍 API 消耗四个症状。不修它,其他数据质量工作都在漏水的桶上做。 |
| **3** | 提案 3 + 7(度量可信度双修) | 监控工具的存在意义是数据可信:daily_tracker 正在静默混用两套口径,走势图正在展示合成历史。两者都是 S 级工作量的真 bug/真污染,修复后"每天看到的数字"才值得信。 |

提案 4(VACUUM+备份演练)紧随其后——磁盘只用 24% 不构成紧急,但**恢复演练从未做过**这点应尽快补课。提案 5 价值最大但风险最高,建议放在 1-4 落地、备份演练通过之后再做。

---

## 附:本次审查未动的东西

- 未修改任何代码/数据/配置;未重启服务;DB 全部 `mode=ro` 查询;Steam API 仅 GET 探针(与应用自身行为一致)。
- 量化引擎(quant_engine.py 935 行)按用户决定保留作 showcase,仅建议清数据不建议删代码。
- 本报告文件:`docs/architecture-review-2026-06-10.md`(唯一新增文件)。
