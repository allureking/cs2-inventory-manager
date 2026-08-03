# cs2-inventory-manager 只读审计报告

**日期**：2026-08-02
**基线**：`main` @ `35292c2`（v0.13.5），工作区干净
**测试基线**：`python3 -m pytest -q` → **472 passed**（用户提及的 301 是旧数字）
**代码规模**：`app/` 11,395 行 · `tests/` 6,546 行 · `static/app.js` 2,832 行（114 个方法，**零测试覆盖**）· `static/index.html` 2,949 行

**方法**：6 路并行专项静态审计（并发竞态 / 外部 API 降级 / 缓存与资源 / 安全 / 前端竞态 / 量化盘点）+ 我本人用 Playwright 做的运行时观察与生产库只读查询。共 35 条候选发现，其中 **8 条经我亲自复核确证**（下方标 ✅ 已实证），其余为静态分析所得、标注为「待复核」。

**验证状态说明**：标 ✅ 的条目我给出了可复现的实测数据；未标的条目逻辑链清晰但我没有独立复现，实施前建议先自行确认触发路径。

---

## 第 1 节 · 隐藏缺陷

### 🔴 高危

---

#### H1 ✅ 已实证 — 生产库缺失索引，租赁导入把 SQLite 写锁握死 83 秒

- **文件**：`app/services/youpin.py:1159`（查询点）· `app/core/database.py:65`（索引清单）
- **现象**：模型里 `youpin_commodity_id` 声明了 `index=True`（`db_models.py:139`），但**生产库上这个索引不存在**。原因是该列是用 `ALTER TABLE ADD COLUMN` 后补的，而 `create_all(checkfirst=True)` 对已存在的表整表跳过、不补建索引；`database.py:65` 的手工索引清单也没带上它。新建库（所有测试走的路径）索引都在 —— **所以测试永远照不出这个偏差**。
- **我的实测**：
  - 生产 `sqlite_master`：`inventory_item` 上只有 5 个索引，`ix_inventory_item_youpin_commodity_id` **不存在**
  - `EXPLAIN QUERY PLAN` → `SCAN inventory_item`（79,760 行 / 177 MB）
  - 单次查询实测 **23.4ms**（未命中）/ 20.3ms（命中靠后行）
  - × 3,555 件在租 = **推算 83 秒**
  - 生产日志三次实测：91s / 82s / 88s（`共拉取悠悠租出记录` → `租出对账` 的间隔）—— **推算与实测吻合**
- **判断**：**真 bug**（模型声明与生产实际漂移）
- **影响**：`youpin.py:1125-1134` 先把全部在租刷成 unknown 并 `flush()`（**写锁到手**），随后 3,555 次全表扫描，直到 1240 行才 commit —— 整整 83 秒独占 SQLite 写锁。`connect_args timeout=30` → 并发写等满 30s 抛 `database is locked`。踩中路径：① 在 00:00–01:00 任务链窗口手动点同步 → `collect_prices` / `snapshot_portfolio` / `record_lease_income` 的逐件 commit 成片失败，而它们多数只 `logger.warning` 一句就跳过 → **当天数据静默残缺**；② 同时段任何前端写操作直接 500。近 30 天日志里尚未出现 `database is locked`（用户手动同步恰好避开了任务链）—— **定时炸弹，非已爆事故**。
- **建议**：把三行加进 `database.py:65` 的 `_indexes` 列表，下次重启自愈：
  `CREATE INDEX IF NOT EXISTS ix_inventory_item_youpin_commodity_id ON inventory_item (youpin_commodity_id);`（同样补 `youpin_order_id` / `youpin_template_id`）。79k 行建索引 <1s，之后这 83 秒会掉到 1–2 秒。更彻底：`init_db` 里遍历 `Base.metadata` 声明的 Index 逐个 `CREATE INDEX IF NOT EXISTS`，杜绝以后再漂移。
- **修复风险**：**低**（纯加索引，不改逻辑）
- **需要你决策**：否

---

#### H2 ✅ 已实证 — 全量导入的单步异常不 rollback，下一步 commit 会把「全部置 unknown」永久落库

- **文件**：`app/api/routes/youpin.py:436`
- **现象**：`_run_import` 用**同一个 session** 串跑 stock→lease→buy→sell，`except Exception` 只记错误就 `continue`，**既不 `db.rollback()` 也不换 session**。非 DBAPI 异常不会让 SQLAlchemy 把事务标成 inactive，前一步已 flush 未 commit 的改动原封不动留在事务里，被下一步的 commit 一起写进去。
- **我的实证（代码链路逐行确认）**：
  - `youpin.py:1125-1132` → `UPDATE ... SET status='unknown' WHERE status='rented_out' AND class_id='YOUPIN'`（全部 ~3,555 件）
  - `youpin.py:1134` → `await db.flush()` —— **进事务、拿写锁，未提交**
  - `youpin.py:1240` → 才 `await db.commit()`
  - 中间循环（1138–1238）抛任何非 DB 异常 → 被 `routes/youpin.py:436` 吞掉 → `import_buy_records` 结尾的 commit 落库
- **判断**：**真 bug**（事务边界的正确性被寄托在调用方身上，而调用方没做）
- **影响**：**这是 v0.13.3「导入对账完整性闸」要防的那场事故的另一条入口** —— 闸判的是「抓取是否完整」，而这里抓取是完整的、是循环中途炸了，闸完全拦不住。后果：3,555 件在租资产（约 ¥278 万）整体掉出 `ACTIVE_STATUSES`，全站件数/成本/市值/PnL 全塌。可抛点：`1139` `rec.get("commodityInfo") or {}` 若上游返回 list 则 AttributeError；`1162` `scalar_one_or_none()` 在 commodity_id 重复时抛 MultipleResultsFound（该列无 unique 约束）。注意 `_STEPS_QUICK`（stock,lease）反而安全 —— lease 是最后一步，异常后 `async with` 退出即 rollback。**只有「全量导入」这个按钮踩雷**。
- **建议**：① `except` 分支里先 `await db.rollback()` 再继续（一行）；更稳的是把 `async with AsyncSessionLocal() as db:` 挪进 for 循环，每步独立 session。② `import_lease_records` 内部自己 try/except 包住 1125–1240，异常时显式 rollback 后再抛。
- **修复风险**：**低**
- **需要你决策**：**是** —— 「单步失败不阻塞后续」是当初有意的设计，改成每步独立 session 会改变这个语义（前一步的成功结果仍保留，但失败步的部分写入会被丢弃）。需要你确认这个取舍。

---

#### H3 ✅ 已实证 — CSQAQ「历史最高价」靠猜字段名，六个键全部不存在，写了 27,407 行垃圾

- **文件**：`app/services/csqaq.py:265`
- **现象**：代码依次尝试 `max_price / highest_price / history_max_price / ath_price / max_sell_price / sell_price_max` 六个键找 ATH，全 miss 后 fallback 去扫 `sell_price_{1,7,15,30,90,180,365}` 取 max 当历史最高价。
- **我的实测**（从生产 IP 发一次只读 GET，CSQAQ token 绑定 IP）：
  - 真实响应 **96 个字段，代码猜的 6 个键一个都不存在**
  - `sell_price_*` 实际值：`sell_price_15 = -328.0`、`sell_price_180 = -4800.0`、`sell_price_365 = -20045.5` —— **全是负数，是「N 日涨跌额」不是价格**
  - 唯一含 max 的真实字段是 `max_float`（磨损值）
  - 生产库 `quant_signal.csqaq_ath_price` 已写入 **27,407 行**，全部 >0。样本：`★ Nomad Knife | Rust Coat` ATH=**¥1.9**、`M4A1-S | Printstream (Factory New)` ATH=**¥46** —— 值域 0.01~12488、均值 348
- **判断**：**真 bug**（语义完全错位：把涨跌额当成历史最高价）
- **影响**：`quant_engine.py:551` 是 `final_ath = api_ath if (api_ath > local_ath) else local_ath` —— 垃圾值偏小时被本地 ATH 顶掉（**这就是它一直没炸的原因**），偏大时会赢并污染 `ath_pct`，进而影响 `near_ath` 告警与卖出评分。
- **建议**：删掉 272–280 的 fallback（`sell_price_N` 在任何情况下都不该当价格用）；把「六个键全 miss」从静默转 fallback 改成 `logger.warning`，让字段名漂移可见。ATH 改用本地 `price_history` 的 `max(close_price)`（`quant_engine.py:620` 已经在算）。另建议一次性把 `csqaq_ath_price` 列清空。
- **修复风险**：**低**
- **需要你决策**：否

---

#### H4 ✅ 已实证 — `role` 字段完全没有鉴权，任何登录用户都能改价/下架

- **文件**：`main.py:113`
- **现象**：`SessionAuthMiddleware` 只判断 session 是否有效，验证通过就放行，**全仓 0 处代码读 `role` 做授权决策**。
- **我的实测**：grep 全库 `role` 只有 4 类出现 —— `db_models.py` 存字段、`auth.py:79/97` 与 `services/auth.py:122` 把 role 回给前端、`main.py:116` 给 api-key 通道硬编码 super_admin。**没有任何一处是鉴权判断**。
- **判断**：**真 bug**（授权层实际不存在，只有「登录 / 未登录」两态）
- **影响**：`scripts/create_user.py` 明确提供 `--role viewer`，等于邀请用户建只读账号；一旦真建了，那个人拿到的是对真金白银悠悠货架的完全控制权（改价 / 下架 / 覆盖凭证）与全部财务数据的读写权。**今天生产只有 admin 一个 super_admin 账号，所以当前实际爆炸半径为 0** —— 但在「你新建第二个账号」那一刻立即变成 high。
- **建议**：二选一 ——
  **(A) 承认这是单用户系统**：把 `create_user.py` 的 `--role` choices 砍成只剩 super_admin，前端不显示 role 徽章，文档写明「role 保留但未实现分级」，消除误导。（约 30 分钟）
  **(B) 真做 RBAC**：加 `require_role(*roles)` 依赖，按「写 = admin+ / 悠悠真操作 = super_admin」分级挂到各路由。（半天到一天）
- **修复风险**：**低**（A）/ **中**（B，需逐个端点分级，容易漏）
- **需要你决策**：**是**

---

#### H5 ✅ 已实证 — 概览页不可见时 `_renderTopGrid` 进入永不终止的 rAF 空转，且会叠加

- **文件**：`static/app.js:1593`
- **现象**：`doLayout` 在 `w < 10` 时无条件递归 `requestAnimationFrame(doLayout)`，**没有任何终止条件**。切到别的 tab 时 `#topGrid` 被 `x-show` 置 `display:none` → `offsetWidth` 为 0 → 永久自旋。
- **我的实测**（真实点击 tab 按钮，非程序化改 state）：

  | 阶段 | 2 秒内 rAF 调用次数 |
  |---|---|
  | 切走后第 1 条链 | **143**（≈60fps） |
  | 再过 2 秒 | **120**（永不终止） |
  | 叠加 3 条链后 | **422**（≈3 倍） |
  | 切回概览 | **0**（恢复正常） |

  自动刷新每 5 分钟调一次 `renderOverviewCharts`，所以链会持续叠加。
- **判断**：**真 bug**（资源泄漏，非崩溃）
- **影响**：用户停在非概览 tab 时，后台以 60fps × N 条链空转，持续吃 CPU / 耗电。移动端尤其明显。不影响数据正确性。
- **建议**：`doLayout` 加终止条件 —— 例如重试上限（`let tries=0; if (++tries > 60) return;`），或只在 `activeTab==='overview'` 时续帧，或改用 `ResizeObserver` 替代自旋。
- **修复风险**：**低**
- **需要你决策**：否

---

### 🟡 中危

---

#### M1 — Steam 库存同步的「消失即改状态」没有完整性闸

- **文件**：`app/services/steam.py:308` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（静态分析，待复核）*
- **现象**：`fetch_inventory_pages` 拿到了 `total_inventory_count` 却从不用它校验实际抓了多少；分页在 `more_items` 为假时直接 break，页面截断不报错。`steam.py:83` 那句 warning「无 Cookie，仅可见公开物品」是代码自己承认视图残缺，但**只 log 不改控制流**，后面照样拿残缺数据做对账 —— 本地 `in_steam` 但本次没出现的行全部改状态。
- **触发**：生产 `.env` 里 Steam cookie 已配置但会自然过期。cookie 过期 → Steam 仍返回 200 + 公开子集（不含 7 天保护期物品）→ 一次同步就把保护期内的物品判定为「消失」。
- **影响**：与 v0.13.3 修的租赁侧同类问题，但 Steam 这一侧的闸**还没有**。
- **建议**：照抄 `import_stock_records` 的完整性闸写法 —— 抓取量显著少于 `total_inventory_count` 时跳过对账并记录原因。

#### M2 — `cleanup_old_snapshots(keep_days=3)` 无条件删，上游连挂 3 天会抹掉本地兜底价格

- **文件**：`app/services/collector.py:618` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：每天 01:00 无条件删除 3 天前的 `price_snapshot`，不检查还剩不剩新鲜数据。
- **影响**：SteamDT 连挂 3 天 → 清理任务照删 → 本地价格基准清零 → 全站市值/PnL 失去数据源，且 v0.13.4 的低价防线也会因「查不到基准」全面 fail-open。
- **建议**：删除前先确认保留窗口内仍有数据（例如 `HAVING COUNT(*) > 0` 或保底保留最近 N 个快照批次）。

#### M3 — 所有会改动 overview 统计口径的写端点都不失效缓存

- **文件**：`app/api/routes/dashboard.py:635` 等 · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核，但 agent 给出了实测复现）*
- **现象**：`invalidate_overview_cache()` 全仓只有 3 处调用方，而 `set_manual_price` / `patch_cost` / 状态修正 / 悠悠导入提交后一个都不失效。
- **影响**：填手动购入价 → PATCH 成功、详情面板立刻变了 → 顶部统计卡的总成本 / 覆盖率 / PnL **最长 4 小时纹丝不动**。用户会以为「保存没生效」而重复操作。
- **建议**：各写路径 commit 后补一行 `invalidate_overview_cache()`。**注意必须先修 M4，否则重启后 4 小时内这行调用照样无效。**

#### M4 — `invalidate_overview_cache` 把 ts 置 0，但 `time.monotonic()` 是「开机以来秒数」

- **文件**：`app/api/routes/dashboard.py:277` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：失效逻辑是 `ts = 0`，而新鲜判断是 `monotonic() - ts < TTL`。主机开机不满 4 小时时 `monotonic()` 本身 < 14400，`0` 反而被判成「新鲜」→ **失效指令完全无效**。
- **备注**：这与我在 v0.13.0 CI 三连红时修的是**同一类 bug**（当时测试夹具用 `ts=0.0`，在新启动的 CI VM 上被判成新鲜），修法也一样：用 `monotonic() - 9999` 或代次计数器。
- **建议**：改用代次计数器（见 M5），一次解决两个问题。

#### M5 — overview / chart-data 缓存「丢失失效」竞态

- **文件**：`app/api/routes/dashboard.py:443` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：handler 读缓存 → 中间多个 await → 写回 `data` + 新 `ts`。若这期间别的协程调了 `invalidate`，那次失效会被飞行中的请求用**旧数据 + 新时间戳**覆盖掉。
- **影响**：点「刷新市价」，进度条走到 100%，总览数字纹丝不动，刷新页面也没用，最长钉死 4 小时。**这正好对得上历史上「刷新完看不到新数据」的体感。**
- **建议**：加单调递增代次：`invalidate` 时 `gen += 1`；handler 开始前记 `gen`，写回时 `if gen == 当前gen` 才落缓存。约 6 行，同时解决 M4。

#### M6 ✅ 已实证 — 登录限速表 `_fail_log` 可被外部无限撑大

- **文件**：`app/services/auth.py:153`
- **我的实测**：限速 key = `f"{_client_ip(request)}:{body.username}"`（`auth.py:63`）—— **用户名维度完全由攻击者控制**。`throttle_hit` 用 `setdefault(key, []).append(...)`；`throttle_locked` 只把该 key 的列表剪成 `[]`，**不删 key**；只有登录成功才 `pop`。
- **判断**：**真 bug**（无界增长且外部可驱动）
- **影响**：持续用随机用户名打登录接口 → 字典无限增长。单条 entry 很小，属于慢速内存耗尽，不是立即可用的 DoS。
- **建议**：`throttle_locked` 里 `if not fails: _fail_log.pop(key, None)`；或定期清扫过期 key；或改用固定容量的 LRU。

#### M7 — `#priceChart` 在 `x-if` 内，永远拿不到观察器

- **文件**：`static/app.js:1526` · **判断**：真 bug · **修复风险**：低 · **需决策**：**是** · *（待复核）*
- **现象**：`_setupChartObservers` 被 `_chartsSetup` 保护成一次性执行且在 init 的 `$nextTick` 跑，此时 `#priceChart` 还在 `<template x-if="itemSignals">` 里、DOM 中不存在 → 六张图里唯独它没有任何 IO/RO 兜底。
- **触发**：在「量化分析 → 饰品分析」点一个饰品，趁请求在途切到别的 tab；响应返回时容器被 x-if 插入但祖先 `display:none` → 宽度 0 → 直接 return，且没有任何观察器记录这次失败。切回来：周边卡片全正常，**唯独价格走势图静默空白**。
- **建议**：(a) 把容器挪到 x-if 外，让它和其它五张一样在 init 时就存在；或 (b) 在 `loadItemSignals` 的 `$nextTick` 里补调 `_renderWhenVisible`。
- **需决策原因**：(a) 会改变 DOM 结构（空状态下也存在一个空容器），(b) 是加性但多一处调用点。

#### M8 — 主题切换时图表停在旧主题

- **文件**：`static/app.js:2577` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：`document.startViewTransition(apply)` 把 class 翻转推迟到下一帧，而图表重绘在 `$nextTick` 就跑完了 —— 重绘时读到的还是旧主题，`renderPortfolioChart` 的指纹（含主题标识）也没变 → early return，图根本不重建。
- **影响**：每次切主题「页面换了、图没换」。纯视觉。
- **建议**：把重绘挂到 `vt.updateCallbackDone.then(...)`，两条分支共用一个 `_redrawAllCharts()`。逻辑不变，只挪时机。

#### M9 — `init()` 把主题落地与所有监听器压在 10 个无超时 fetch 之后

- **文件**：`static/app.js:798` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：`await Promise.all([...10 个请求...])` 之后才做主题落地、`$watch` 注册、观察器安装、resize/matchMedia 监听、骨架清理。
- **影响**：(a) 浅色主题用户每次刷新都先看到深色页面再闪成浅色（FOUC）；(b) 任意一个请求 TCP 挂起不返回 → 统计卡永远停在骨架、主题永远错、**`isNarrow` 冻结 → 旋屏后持仓列表形态不跟随**。
- **建议**：主题落地移到 `<head>` 的 inline script（彻底消除 FOUC）；把不依赖数据的初始化全部挪到 await 之前。

#### M10 — 渲染链没有逐个隔离异常，一处抛错吞掉后面全部图表

- **文件**：`static/app.js:1531` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：`renderOverviewCharts` 顺序裸调四个渲染函数，无 try/catch；`toggleTheme` 的 `$nextTick` 同样裸调五个。项目里其它调用点都包了 try/catch，**唯独这两条链没有**。
- **触发**：最现实的是 CDN 失败 —— `apexcharts` / `chart.js` 走 `cdn.jsdelivr.net`，国内网络被墙或超时时 `Chart` 是 undefined → 第一句就抛 → 后面三张图一个都不执行。
- **建议**：复用 `_renderWhenVisible` 里已有的 `safe()` 模式，逐个包一层。

#### M11 — 并发请求没有序号守卫，先发后到的响应会覆盖新结果

- **文件**：`static/app.js:1313` · **判断**：真 bug · **修复风险**：低 · **需决策**：否 · *（待复核）*
- **现象**：`loadPortfolioHistory` / `loadItems` / `loadItemSignals` 都是「发请求 → await → 无条件写全局 state」，无序号 / AbortController。
- **触发**：概览页快速点时间范围 `90d` 再点 `all`，若 90d 后到 → 数据是 90d 的，而按钮高亮和「N 个数据点」是 all 的。
- **备注**：我做的运行时乱序测试（首个响应故意延迟 1.5s）**没有观察到崩溃**，但那只验证了「不崩」，没有验证「数据是否被旧响应覆盖」—— 这条讲的是后者，属于正确性问题而非稳定性问题。
- **建议**：每个 loader 加自增令牌，await 之后写 state 之前判一次。

#### M12 ✅ 已实证 — 生产数据库文件权限 0644

- **文件**：生产 `/var/www/cs2-inventory-manager/cs2_inventory.db`
- **我的实测**：`-rw-r--r-- 1 cs2app cs2app 177262592`
- **判断**：**真 bug**（最小权限原则）
- **影响**：同机任何其他服务用户可直接读走密码哈希与全部财务数据。该机是 co-tenant（还跑着 web / 其他项目）。
- **建议**：`chmod 640`（+ 确认 `-wal` / `-shm` 同样处理）。**注意这是生产文件操作，本轮未执行。**
- **修复风险**：低 · **需决策**：否（但需要你同意在生产执行）

---

### 🟢 低危 / 改进机会

| 编号 | 文件:行 | 现象 | 判断 | 风险 |
|---|---|---|---|---|
| L1 | `main.py:204` | 启动时三个后台任务用裸 `create_task`，绕开了 `app/core/tasks.py` 专门为此建的 `spawn()`。其中 `run_credential_sentinel()` 整段都在 await HTTP，是典型可回收态 —— 被 GC 则启动时的凭证探测静默消失，且无日志 | 改进机会 | 低 |
| L2 | `app/services/collector.py:121` | `collect_prices` 全批失败仍报 DONE/idle 并刷新 `last_run`，监控无法区分「全成功」与「全失败」 | 改进机会 | 低 |
| L3 | `static/app.js:1582` | `_renderTopGrid` 用 `innerHTML` 拼第三方来的 `icon_url`/`name`，属性未转义 → 存储型 XSS 落点。需先污染上游（悠悠/CSQAQ）才能触发，但一旦触发就是 admin 会话上的任意操作 | 真 bug | 低 |
| L4 | `app/services/youpin.py:363` | `POST /api/youpin/auth/login` 把完整悠悠 Bearer Token 原样回给前端，而前端根本不用它 | 改进机会 | 低 |
| L5 | `static/index.html:2292` | 更新日志 tab 用 `x-show`，24 个版本 / 177 条目在首屏就全量建树（v0.13.4 修持仓列表时的同类残留） | 改进机会 | 低 |
| L6 | `static/app.js:659` | `theme='system'` 不持久化，刷新后静默退回 `dark`；系统主题变化也不跟随 | 真 bug | 低 |

---

## 第 2 节 · UI 缺陷（我本人实测，证据完整）

### U1 ✅ 已实证 — 641–871px 区间顶栏溢出、按钮变形、两个按钮完全不可点

**你的假设成立，我把它量化了。**

- **文件**：`static/index.html:320`（`@media (max-width: 640px)` 块）· `static/index.html:460`（`.nav-actions`）
- **破坏区间**：**641px – 871px**（872px 起恢复正常）

| 视口宽度 | 页面横向溢出 | 顶栏高 | 顶栏内控件数 | 被推出视口的控件 |
|---|---|---|---|---|
| 640 | 0 | 115px | 7 | 0 |
| **641** | **231px** | 57px | 12 | **3** |
| 700 | 172px | 57px | 12 | 2 |
| 768 | 104px | 57px | 12 | 2 |
| 860 | 12px | 57px | 12 | 1 |
| **872** | **0** | 57px | 12 | 0 |

**「变形」的具体机制**：641px 起导航按钮从 `76×40` 被 flex 压成 **`40×76`** —— 宽度挤到 40px，文字竖排堆成两行，按钮成了细高条。「同步库存」「匹配记录」被推到 `right=802/872`（视口仅 768）—— **不横向滚动根本点不到**。另有 3 个控件高度仅 23px（`中` 26×23、`🌙` 28×23、头像 20×20），桌面端点击目标偏小。

**根因归因（实测确证）**：运行时隐藏顶栏 → 页面溢出 **172 → 0**。所有 tab 的溢出数值完全一致（700px 都是 172、768px 都是 104），且 `.tbl-wrap` 自身溢出为 0 —— **内容区响应式是好的，问题 100% 在顶栏**。

原因：`@media (max-width: 640px)` 里有四条规则协同工作 —— `.nav-inner` 允许换行、`.nav-mobile-bar` 显示汉堡、`.nav-tabs` 独占一行可横滚、**`.nav-actions { display: none }`** 把 406px 的动作区收起来。641px 起这四条**同时失效**，动作区被强制内联。导航区 466px + 动作区 406px = **需要 872px**，与实测阈值分毫不差。

**建议方案**（已在浏览器验证，但按要求未实施）：新增一段 `@media (min-width: 641px) and (max-width: 880px)`，复用现成的折叠机制（`.nav-open` 由 `mobileMenu` 驱动，开关按钮已存在于 `.nav-mobile-bar`）。

**实测验证结果**：注入候选 CSS 后 —— 641/700/768/860/880px 溢出**全部归零**；≥900px 完全不受影响（顶栏仍 57px、溢出 0）；点真实的「更多」按钮，抽屉正常展开（684px 宽、无溢出、零报错）。`--hdr-h` 由 JS 自动跟随实际顶栏高度（640px 时 115、以上 57），所以 token 过期横幅会自动跟上，无需额外处理。

- **修复风险**：**低**（纯加性 media query，不改动任何现有规则；不影响 ≤640 移动端与 ≥881 桌面端）
- **需要你决策**：**是** —— 需要你确认「641–880px 采用折叠式顶栏」这个产品取舍。平板横屏用户会从「所有按钮平铺」变成「点更多展开」。备选方案：精简顶栏元素（把「同步库存」「匹配记录」常驻收进菜单），但那会改变桌面端信息架构。

### U2 ✅ 已实证 — 其余响应式中间态：未发现问题

- **表格 / 卡片 / 图表容器**：五个 tab × 700/768/900px 全部实测，`.tbl-wrap` 自身溢出恒为 0，无越界
- **模态框**：结构为 `fixed inset-0` 全屏遮罩 + 内层 `max-w-sm`(384px) + `max-height:90vh; overflow-y:auto` —— 任何宽度下都不会溢出
- **浅色主题**：与深色表现完全一致，问题与主题无关

### U3 ✅ 已实证 — 图表崩溃修复是彻底的（含一处方法学更正）

运行时压力测试（**真实点击**，非程序化改 state）：24 次快速切 tab + 10 次切主题 → **零报错**，4 个 canvas 全部健康（无 0 尺寸、无游离）。另做请求乱序测试（首个响应故意延迟 1.5s 制造后发先至）→ 同样零报错。

> **更正**：我在上一轮汇报里说过「20 次快速切 tab 零报错」，那次用的是 `Alpine.raw(...)` 直接改 `activeTab` —— 而 `Alpine.raw()` 返回未包装对象，**改它不触发响应式，tab 实际根本没切**。上表是改用真实点击后重做的结果。结论不变（仍是零报错），但当时那条证据是无效的。H5 的 rAF 空转也正是换成真实点击后才复现出来的。

---

## 第 3 节 · 量化分析板块（可行性评估，非开发方案）

### 现状盘点

**✅ 已实证的关键事实**：
- `quant_signal` 38,528 行，`max(signal_date) = 20260801`（看起来很新鲜）
- **但近 5 天每天 244 行，`opportunity_score` 全部为 NULL**
- 最后一次有 `sell_score` 的日期是 **20260702** —— **信号计算已停摆一个月**
- 每天那 244 行是 CSQAQ 同步（00:02）写的，只填租金/存世量，**技术指标列全空**
- `quant_alert` 19,428 行，其中 `spread_arb` 10,444（54%）+ `near_ath` 7,658（39%）= **93% 是噪声**
- `lease_income_daily` **200,909 行 / 52 天 / 234 品** —— 全库最有商业价值又最没被消费的数据

**结论：量化分析板块目前除「跨平台套利」子 tab 和 CSQAQ 三个数值外，基本是空壳，且用户无从察觉**（新鲜度条显示「信号 今天」）。

### 用现有数据就能做（你倾向的这一类）

| 编号 | 方向 | 需要的数据 | 动哪端 | 工作量 | 风险 | 需决策 |
|---|---|---|---|---|---|---|
| **Q1** | **恢复 `daily_signals` 定时计算** —— 这是解锁下面一切的前提 | 现有（`price_history` platform=ALL 实测 234 品 × 61 天连续无缺、无 0 值污染） | 后端（取消一行注释 + 改时刻） | 1–2 小时 | **中** | **是** |
| **Q2** | **告警噪声治理** —— `_calc_spread_map` 排除 STEAM（与 `/spreads` 端点对齐）、调 `spread_arb` / `near_ath` 阈值 | 现有 | 后端（一行 SQL + 配置） | 1 小时 | 低 | **是** |
| **Q3** | **新鲜度条改成看「有评分的最新日」** —— 现在 CSQAQ 写的行冒充了信号日期，掩盖了 Q1 停摆一整月 | 现有 | 后端 WHERE + 前端一个条件 | 30 分钟 | 低 | 否 |
| **Q4** | **「排名」子 tab** —— `rankings` 端点的 16 列排序 / 分类筛选 / 搜索 / 分页**全部写好了，前端零入口** | 现有 | **纯前端** (~60 行) | 半天 | 低 | 否 |
| **Q5** | **租赁实绩排行** —— `/lease-income/rankings` 端点写好了，前端零调用；20 万行数据在等着 | 现有 | **纯前端** (~40 行) | 2–3 小时 | 低 | 否 |
| **Q6** | **买入机会榜** —— 六维模型 `opportunity_score` 已完整实现并落库，界面只在个股详情露一个数字，等于「只能验证不能发现」 | 现有 | 后端 10 行 + 前端一张表 | 2–3 小时 | 低 | **是** |
| **Q7** | **组合 vs 大盘** —— `daily_tracker` 254 天（含 v0.13.5 刚接的 `steamdt_index`）+ `portfolio_snapshot` 1,356 行，两条序列**同刻对齐**，但从未一起展示 | 现有 | 后端一个端点 + 前端一张双线图 | 半天 | 低 | **是** |
| **Q8** | 个股价格图支持平台切换（`/price-history` 已支持，前端写死 `platform=ALL`） | 现有 | 纯前端 | 1 小时 | 低 | 否 |
| **Q9** | 展示已落库但从不显示的信号列（`bb_width` / `ma_7` / `ma_30` / `annualized_return`） | 现有 | 纯前端 | 1–2 小时 | 低 | 否 |
| **Q10** | `quant_alert` 19,428 行无任何清理任务 | 现有 | 后端（加清理任务） | 1 小时 | 低 | 否 |

### 需要新采集的

**本轮未发现值得新增采集的方向。** 现有数据的利用率还很低（`lease_income_daily` 20 万行零消费、`rankings` 端点 90% 能力浪费），建议先把上表做完再谈新数据源。

### 依赖关系（重要）

**Q1 是总开关**：Q4 / Q6 / Q9 的表格在信号未恢复前全是空列。
**Q2 必须在 Q1 之前做**：否则一恢复计算就立刻每天新增 ~250 条噪声告警。

---

## 建议实施顺序

### 第一批：低风险高收益，可无人值守

1. **H1** 补三个索引 — 83 秒写锁 → 1–2 秒，纯加性，测试可验证
2. **H3** 删 CSQAQ ATH 的错误 fallback + 清空脏列
3. **M6** 限速表加清理（一行）
4. **L1** 三处 `create_task` → `spawn()`
5. **M4 + M5** 缓存代次计数器（一次解决两个）
6. **M3** 各写路径补 `invalidate_overview_cache()`（**必须在 M4/M5 之后**）
7. **H5** rAF 空转加终止条件
8. **Q3** 新鲜度条口径修正

> 这一批全部有明确判据、改动局部，且大多可由现有 472 个测试兜底。建议每条配回归锁 + 破坏性验证。

### 第二批：需要你在场看效果

9. **U1** 顶栏中间态折叠 — 需要你看一眼 641–880px 的实际观感是否接受
10. **M8** 主题切换图表重绘时机 — 需要你切几次主题确认
11. **M9** 主题落地提前 / FOUC — 需要你刷新几次确认闪烁消失
12. **M7** `#priceChart` 观察器 — 需要你在量化分析页实操验证

### 第三批：需要你先拍板方向

13. **H4** role 鉴权 — 先定 A（承认单用户）还是 B（真做 RBAC）
14. **H2** 全量导入事务边界 — 先定「单步失败不阻塞后续」这个语义要不要保留
15. **M12** 生产 DB 权限 chmod 640 — 生产操作，需你同意
16. **Q2 → Q1** 告警治理 → 恢复信号计算（**必须按这个顺序**）
17. **Q4 / Q5 / Q6 / Q7** 量化板块补全 — 建议 Q5（租赁实绩排行）先做，它不依赖 Q1 且数据最厚

### 建议暂缓

- **M1**（Steam 完整性闸）、**M2**（快照清理保护）：都是「上游长时间降级」才触发的场景，重要但不紧急，建议与 Q1 同批处理
- **M10 / M11 / L2–L6**：真实但影响面小，可作为后续清理批次

---

## 声明

**本轮审计严格只读。未修改任何代码文件、未创建除本文件外的任何仓库文件、未 commit、未 push、未部署、未重启任何服务、未修改任何生产数据。**

- 所有生产库查询均使用 `sqlite3 -readonly` 或 `mode=ro` URI
- 唯一一次对生产的写操作可能性（CSQAQ 字段验证）是一次 HTTP **GET**，无副作用
- 浏览器验证在本地静态 harness（`127.0.0.1:8901`，独立 stub 服务）上进行，其中「候选修复方案」的 CSS 仅通过 `page.add_style_tag` 注入到运行中的浏览器实例，**未写入任何项目文件**
- 工作区在审计前后均为 `git status --porcelain` 干净（除本文件外）

**验证边界**：标 ✅ 的 8 条（H1–H5、M6、M12、U1–U3）附有我本人的可复现实测数据；其余条目来自静态源码分析，逻辑链完整但我未独立复现，实施前建议先确认触发路径。
