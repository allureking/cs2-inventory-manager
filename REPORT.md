# 后端测试套件 — 交付报告 (auto/test-suite)

隔离 worktree：`/home/kingk/projects/cs2-overnight`，分支 `auto/test-suite`（基于 main @ f930cff）
运行：`cd /home/kingk/projects/cs2-overnight && python3 -m pytest -q`
覆盖率：`python3 -m pytest --cov=app --cov-report=term-missing --cov-report=html`（HTML 在 `htmlcov/`）
结果：**301 passed**，退出码 **0**，5 warnings（均为被测代码的 deprecation,见 §2）。

dev 依赖（本轮新增,仅测试/构建用,未碰 app/）：`pytest-cov`、`python-multipart`（后者 prod 亦依赖）。

---

## 1. Gap 清单 close 情况

第一步对照 app/ 重新审计,gap 清单写在 PROGRESS.md。本轮按其补齐：

- **每个 app/ 模块都不再被静默漏掉**：要么有有意义测试，要么其外部部分在 §3 明列。
- 第二轮新增 11 个测试文件（143 用例）：quant_engine 指标/评分、薄路由(items/prices/tracker)、
  dashboard /items 与 manual-price、inventory 写端点、analysis DB-read 端点、steam 服务 DB 部分、
  quant 告警规则/分类、collector OHLC 聚合、youpin/listing 只读路由与状态、steamdt/csqaq 纯 helper。
- 第一轮 8 个文件（158 用例）保留。

## 2. 测试文件与用例总数

- 测试文件：**19 个**（+ `tests/conftest.py` 基建）
- 用例总数：**301**（第一轮 158 + 第二轮 143）

| 文件 | 用例 | 模块 |
|---|---|---|
| test_tracker_model.py | 32 | 租赁年化模型/常量/解析 |
| test_pricing.py（原有） | 19 | calc_sell_price / calc_lease_price |
| test_pricing_query.py | 14 | pricing.get_latest_prices / get_all_latest_prices |
| test_tracker_crud.py | 19 | tracker CRUD/月度聚合/Excel |
| test_youpin_pagination.py | 16 | 分页 loop-until-empty |
| test_youpin_parsers.py | 30 | youpin 记录解析 |
| test_dashboard_api.py | 15 | dashboard overview/chart-data |
| test_routes_misc.py | 13 | monitoring / inventory 只读 |
| test_quant_engine.py | 40 | 技术指标 + 卖出/买入评分 |
| test_routes_thin.py | 11 | items / prices·cached / tracker GET |
| test_units_misc.py | 6 | _normalize_shelf_item / get_latest_snapshots |
| test_analysis_api.py | 19 | analysis DB-read 端点 |
| test_inventory_writes.py | 9 | inventory cost/bulk/status/refresh |
| test_dashboard_items.py | 12 | dashboard /items 过滤排序分页 + manual-price |
| test_steam_service.py | 8 | steam DB 部分 + BUFF-only 盈亏 |
| test_quant_alerts.py | 18 | 分类 / YAML 告警规则覆盖 / 指标聚合 |
| test_collector_aggregate.py | 5 | aggregate_daily(OHLC) / cleanup |
| test_youpin_listing_routes.py | 6 | youpin 状态 / listing 快照只读 |
| test_steamdt_csqaq_units.py | 9 | steamdt/csqaq 纯 helper |

## 3. 覆盖率摘要

总体：**42%**（line）。说明：模块「总行数」被大量**外部 IO 代码**（HTTP 客户端 / RSA-AES / 调度）摊薄；
**核心业务逻辑分支是高覆盖的**，外部 IO 已在下方显式声明「故意不覆盖」。

核心模块（核心逻辑已覆盖；剩余多为该模块内的外部 IO 分支）：
| 模块 | 覆盖 | 说明 |
|---|---|---|
| services/pricing.py | 100% | 全覆盖 |
| core/constants.py | 100% | ACTIVE_STATUSES |
| services/tracker.py | 75% | 模型/CRUD/月度全覆盖；snapshot_daily(外部悠悠)未覆盖 |
| services/quant_engine.py | 46% | 指标/评分/告警规则/指标聚合全覆盖；compute_all_signals 异步管线(DB+外部)未覆盖 |
| api/routes/dashboard.py | 39% | overview/items/chart-data/manual-price 覆盖；后台价格刷新(外部)未覆盖 |
| services/youpin_listing.py | 37% | calc_sell/lease + _normalize 覆盖；上架/改价 HTTP 未覆盖 |
| services/steam.py | 36% | DB 估值/盈亏覆盖；Steam Web API 抓取未覆盖 |
| api/routes/youpin.py | 30% | 状态端点覆盖；登录/同步/导入(外部)未覆盖 |
| services/youpin.py | 27% | parsers + 分页 loop 覆盖；HTTP 客户端 + 加密未覆盖 |
| api/routes/analysis.py | 28% | DB-read 端点覆盖；compute/backfill/csqaq-sync(外部)未覆盖 |
| api/routes/listing.py | 42% | 快照只读覆盖；上架/下架动作(外部)未覆盖 |
| services/collector.py | 24% | aggregate_daily/cleanup 覆盖；采价/快照编排(外部)未覆盖 |
| services/steamdt.py / csqaq.py | 27% / 12% | 纯 helper + DB 部分覆盖；API 客户端未覆盖 |

### 故意不覆盖（外部 IO / 网络客户端 / 调度，单测范围外）
以下需真实网络/外部凭证，单元测试无法在不连外网的前提下有意义地覆盖；其**纯逻辑部分已单独单测**：
- `services/youpin.py` 的 HTTP 客户端、RSA/AES 加密、各 `fetch_*`（真实悠悠 API）
- `services/steam.py` 的 Steam Web API 抓取/解析（库存同步）
- `services/steamdt.py` / `services/csqaq.py` 的 API 客户端（`fetch_*` / `sync_*` / `build_id_mapping`）
- `services/collector.py` 的 `collect_prices` / `snapshot_portfolio` / `backfill_avg_prices`（编排外部采集）
- `routes/youpin.py`（登录、SMS、模板同步、库存/租赁/买卖导入）、`routes/listing.py`（上架/改价/下架/智能改价）
- `routes/analysis.py` 的 `/backfill` `/compute-now` `/csqaq-sync`（触发后台任务 + 外部）
- `routes/dashboard.py` `/refresh-prices`、`routes/inventory.py` `/sync` `/refresh-prices`（外部批量拉价）
- `core/database.py` 的 `init_db`（建表/迁移）— 通过测试基建间接建表，未直接断言迁移 SQL

## 2'. 真实 bug / 观察清单（已记录未修）

**无确认 bug**（无需 xfail）。4 条观察项，已加 characterization 测试锁定当前行为：

1. **`services/youpin.py:878`** `datetime.utcfromtimestamp()` 已弃用（Py 3.12+，未来移除）。功能正常，仅 DeprecationWarning。锁定：test_youpin_parsers `_parse_date`。建议改 `datetime.fromtimestamp(ms/1000, tz=timezone.utc)`。
2. **`api/routes/monitoring.py:121`** `Query(..., regex=)` 已弃用（应 `pattern=`）。锁定：test_routes_misc 非法 range→422。
3. **`services/steam.py:399-400`** `get_inventory_with_prices` 的逐件盈亏只用 **BUFF** 价；而 `dashboard` overview/chart-data 用**跨平台最低价**。两处口径不一致（设计差异，非 bug）。锁定：test_steam_service `test_profit_none_without_buff_even_if_youpin_present`。
4. **`api/routes/analysis.py:912`** search-items 用 `.distinct(col)`（DISTINCT ON）——SQLite 静默忽略且 SQLAlchemy 已弃用，未来版本将报错。当前结果靠数据本身去重。锁定：test_analysis_api `test_search_items_by_name`。

## 4. 红线声明

- ✅ **未触碰线上 serve 文件**：仅在隔离 worktree `auto/test-suite` 分支；未改 `static/`、未碰主仓 working tree。
- ✅ **未部署 / 未重启服务 / 未动 nginx**：无 scp、无 systemctl、无 reload。
- ✅ **未 push / 未动 main / 未动 remote**：仅本地 commit。
- ✅ **未碰外部世界 / 真实数据**：全部内存 SQLite + mock / monkeypatch；零真实网络、未连生产 DB。
- ✅ **Additive only**：`git diff main..auto/test-suite -- app/` 为空（未改业务逻辑）；仅新增 `tests/`、`PROGRESS.md`、`REPORT.md`、`.gitignore`(忽略 htmlcov)。

## 5. Review / 合并（由你决定）

```
git -C /home/kingk/projects/cs2-overnight log --oneline main..auto/test-suite
git -C /home/kingk/projects/cs2-overnight diff main..auto/test-suite --stat
cd /home/kingk/projects/cs2-overnight && python3 -m pytest -q
# 覆盖率: python3 -m pytest --cov=app --cov-report=term-missing --cov-report=html && open htmlcov/index.html
# 合并(仅新增 tests/+文档): git checkout main && git merge auto/test-suite
```
