# 测试套件进度 (auto/test-suite)

隔离 worktree：`/home/kingk/projects/cs2-overnight` @ 分支 `auto/test-suite`
运行：`python3 -m pytest -q`
红线：additive only（只加 tests/ + 文档）；不碰 app/ 业务逻辑；不部署/push；全部内存库 + mock,无真实网络。

## 当前状态
✅ 完成 — 8 个测试文件,158 passed(新增 139 + 既有 19),0 失败。详见 REPORT.md。

## 已完成 ✅
- [x] 测试基建 `tests/conftest.py`：`memory_db()` 内存库会话、`asgi_client()` ASGI 客户端(不触发 startup)、`make_item/make_snapshot` fixtures
- [x] `tests/test_tracker_model.py`(32 用例)：`_calc_annuals`(VIP/非VIP/边界)、常量符合 expected_cycle 公式(S=0/0.85/1、CD=0/8)、`_parse_stats_desc`、`_safe_float/int`

- [x] `tests/test_pricing_query.py`(14 用例)：get_latest_prices / get_all_latest_prices —— 空名单、缺价、跨平台取 min、多分钟只认最新分钟、null/0/负价排除、最新分钟全无效则剔除

- [x] `tests/test_tracker_crud.py`(19 用例)：config kv、daily_records 倒序/范围、monthly VIP10%·非VIP20% 费率与缺天预估/月末库存、update_record 重算、Excel 往返
- [x] `tests/test_youpin_pagination.py`(16 用例 = 8 场景 × buy/sell)：空页/单页不满/满页+空/满页+不满/多满页+空/首页异常/次页异常保留/ MAX_PAGES 上限,mock fetch_*_records

## 待办 📋
- [x] `tests/test_dashboard_api.py`(15 用例)：overview / chart-data 经 ASGI —— ACTIVE_STATUSES 计数/市值口径(空库存/全 in_storage/混合)、PnL(逐件 snapshot vs effective_cost、覆盖率)、异常入参
- [x] `tests/test_routes_misc.py`(13 用例)：tracker GET、monitoring、inventory GET、health — 正常 + 异常入参
- [x] `tests/test_youpin_parsers.py`(30 用例)：_parse_price/qty/date/hash_name/abrade 边界
- [x] REPORT.md 早报

## 既有(未改动)
- `tests/test_pricing.py`(19 用例,calc_sell_price/calc_lease_price)— 仓库原有

## 真实 bug 记录
- 无确认 bug(无 xfail)。3 条观察项(2 弃用 API + 1 PnL 平台口径设计差异)见 REPORT.md §2,已记录未修。

## Checkpoint 提交历史
- (见 git -C ../cs2-overnight log)
