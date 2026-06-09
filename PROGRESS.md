# 测试套件进度 (auto/test-suite) — 第二轮：收口到完整

隔离 worktree：`/home/kingk/projects/cs2-overnight` @ `auto/test-suite`
运行：`python3 -m pytest -q`  覆盖率：`python3 -m pytest --cov=app --cov-report=term-missing --cov-report=html`
红线：additive only(只动 tests/ + 文档 + dev 依赖)；不碰 app/ 业务逻辑；不部署/push；全内存库 + mock。
dev 依赖(本轮新增,仅测试用)：`pytest-cov`、`python-multipart`(后者 prod 亦依赖)。

## 当前状态
🚧 进行中（第二轮）。已把 gap 清单写回本文件并按此补齐核心模块。

---

## Gap 清单（对照 app/ 实际代码）

### A. 已覆盖（有意义测试）
| 模块 | 测试 | 说明 |
|---|---|---|
| services/tracker.py | test_tracker_model + test_tracker_crud | 模型/年化/常量/CRUD/月度/Excel（75%+） |
| services/pricing.py | test_pricing_query | 100% |
| services/youpin_listing.py 计算 | test_pricing(既有) + test_units_misc | calc_sell/lease + _normalize_shelf_item |
| services/youpin.py 纯函数 | test_youpin_parsers + test_youpin_pagination | parsers + 分页 loop（HTTP 客户端见 C） |
| services/quant_engine.py 指标/评分 | test_quant_engine | _sma/_ema/rsi/bollinger/momentum/volatility + 两个 score（异步管线见 C） |
| services/steamdt.py get_latest_snapshots | test_units_misc | DB 部分（API 客户端见 C） |
| services/steam.py DB 部分 | test_dashboard_api + test_routes_misc | summary/inventory_with_prices 经路由（Steam API 客户端见 C） |
| routes/dashboard.py | test_dashboard_api | overview/chart-data（items 列表/manual-price 见 B） |
| routes/monitoring.py | test_routes_misc | status/portfolio-history/data-freshness |
| routes/inventory.py | test_routes_misc | summary/missing-cost/list（写端点见 B） |
| routes/items.py | test_routes_thin | list/search/分页/422 |
| routes/prices.py | test_routes_thin | cached（外部价端点见 C） |
| routes/tracker.py | test_routes_thin | daily/monthly/export（snapshot/import 见 C） |
| routes/analysis.py | test_analysis_api | overview/alerts/search/rankings/categories/price-history/status（compute 见 C） |
| core/constants, config, database(部分), models, schemas | 各测试 import 触发 | 100%/已加载 |

### B. 待补（DB 写端点 / 剩余分支，本轮继续）
- [ ] routes/inventory.py 写端点：PATCH /{asset_id}/cost、POST /bulk-cost、PATCH /{asset_id}/status
- [ ] routes/dashboard.py：GET /items（列表/过滤/排序/分页）、PATCH manual-price、refresh-status
- [ ] services/steam.py：get_inventory_with_prices 的 **BUFF-only 盈亏** characterization（锁观察3）
- [ ] services/quant_engine.py：_get_rules_for_item / _compute_item_indicators_from_cache（可单测的纯/配置部分）

### C. 拟「故意不覆盖」（外部 IO / 网络客户端 / 调度，单测范围外，记 REPORT §2）
- services/youpin.py HTTP 客户端 + RSA/AES 加密 + 各 fetch_*（真实悠悠 API）
- services/steam.py Steam Web API 抓取/解析、services/steamdt.py SteamDT API 客户端
- services/csqaq.py（CSQAQ 外部 API 客户端 + 映射）
- services/collector.py（APScheduler 定时任务，编排外部采集）
- routes/youpin.py、routes/listing.py（悠悠登录/上架/改价/下架等外部动作）
- routes/analysis.py 的 /backfill /compute-now /csqaq-sync（后台任务 + 外部）
- 理由：均需真实网络/外部凭证；纯逻辑部分（parsers/分页/指标/估值）已单独单测。

### D. 观察项（已记录未修，characterization 锁现状）
1. youpin.py:878 `datetime.utcfromtimestamp` 弃用
2. monitoring.py:121 `Query(regex=)` 弃用（应 pattern=）
3. steam.py get_inventory_with_prices 盈亏只用 BUFF 价，与 dashboard 跨平台最低价口径不一致
4. analysis.py search-items `.distinct(col)`（DISTINCT ON）在 SQLite 被静默忽略 + SQLAlchemy 弃用

---

## 终态检查
- [ ] pytest 退出码 0
- [ ] 覆盖率报告已生成（term-missing + html）
- [ ] 本清单全部勾选、无 todo 残留
- [ ] 每个 app/ 模块：有测试 或 REPORT §2 明列「故意不覆盖+原因」
- [ ] REPORT.md 更新（gap close 情况 + 用例数 + 覆盖率摘要 + 观察项 + 红线声明）

## Checkpoint 提交历史
见 `git -C /home/kingk/projects/cs2-overnight log --oneline main..auto/test-suite`
