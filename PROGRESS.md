# 测试套件进度 (auto/test-suite) — 第二轮：已收口

隔离 worktree：`/home/kingk/projects/cs2-overnight` @ `auto/test-suite`
运行：`python3 -m pytest -q`（301 passed, exit 0）
覆盖率：`python3 -m pytest --cov=app --cov-report=term-missing --cov-report=html`（总体 42%，HTML 在 htmlcov/）
红线：additive only（只动 tests/ + 文档 + .gitignore + dev 依赖）；未碰 app/；未部署/push；全内存库 + mock。
dev 依赖（仅测试/构建）：`pytest-cov`、`python-multipart`(prod 亦依赖)。

## 当前状态
✅ **完成**。19 个测试文件、301 用例全绿；覆盖率报告(term + html)已生成；
每个 app/ 模块都有有意义测试或在 REPORT §3 明列「故意不覆盖+原因」。详见 REPORT.md。

---

## 任务清单（全部完成）

### A. 核心逻辑（高分支覆盖）✅
- [x] 租赁模型 期望周期=R+(1-S)×CD（S=0/0.85/1、CD=0/8）+ _calc_annuals（test_tracker_model）
- [x] pricing 取值（最新分钟/跨平台 min/缺价排除）（test_pricing_query 100%）
- [x] 逐件 PnL：VIP10%/非VIP20%（test_tracker_crud 月度）+ effective_cost/manual 覆盖（test_dashboard_api/items）
- [x] youpin 分页 loop-until-empty（test_youpin_pagination）
- [x] ACTIVE_STATUSES 口径：空/全 in_storage/混合（test_dashboard_api / test_routes_misc / test_steam_service）
- [x] quant 指标 RSI/BB/动量/波动 + 卖出/买入评分分支（test_quant_engine 40）

### B. 路由 / 服务 DB 逻辑 ✅
- [x] dashboard overview/chart-data/items/manual-price
- [x] inventory 只读 + 写端点(cost/bulk/status/refresh 校验)
- [x] monitoring status/portfolio-history(422)/data-freshness
- [x] items/prices·cached/tracker GET 薄路由
- [x] analysis DB-read 端点(overview/alerts/search/rankings/categories/price-history/status)
- [x] steam 服务 DB 部分(_batch_latest_prices/inventory/summary)
- [x] quant 告警规则(YAML 覆盖)/_classify_item/_compute_item_indicators_from_cache
- [x] collector aggregate_daily(OHLC+ALL)/cleanup_old_snapshots
- [x] youpin 状态端点 + listing 快照只读路由
- [x] steamdt/csqaq 纯 helper

### C. 故意不覆盖（外部 IO，已在 REPORT §3 明列）✅
- [x] youpin HTTP 客户端/加密、steam/steamdt/csqaq API 客户端、collector 采价编排、
      youpin/listing 外部动作路由、analysis compute/backfill/csqaq-sync、外部 refresh-prices、init_db 迁移

### D. 观察项（characterization 锁定现状,未改代码）✅
- [x] 1 utcfromtimestamp 弃用 / 2 Query(regex) 弃用 / 3 steam BUFF-only 盈亏口径 / 4 search-items DISTINCT ON 弃用
      —— 详见 REPORT §2'

## 终态检查 ✅
- [x] `python3 -m pytest -q` 退出码 0（301 passed）
- [x] 覆盖率报告已生成（term-missing + html）
- [x] 本清单全部勾选、无 todo 残留
- [x] 每个 app/ 模块：有测试 或 REPORT §3 明列「故意不覆盖+原因」
- [x] REPORT.md 更新（gap close + 用例数 + 覆盖率摘要 + 观察项 + 红线声明）

## Checkpoint 提交历史
见 `git -C /home/kingk/projects/cs2-overnight log --oneline main..auto/test-suite`
