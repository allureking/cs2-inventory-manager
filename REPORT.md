# 后端测试套件 — 早报 (auto/test-suite)

隔离 worktree：`/home/kingk/projects/cs2-overnight`
分支：`auto/test-suite`（基于 main @ f930cff）
运行：`cd /home/kingk/projects/cs2-overnight && python3 -m pytest -q`
结果：**158 passed**（新增 139 + 仓库原有 19），0 失败，约 2 秒。

---

## 1. 新增测试文件与覆盖

| 文件 | 用例 | 覆盖 | 关键边缘情况 |
|---|---|---|---|
| `tests/conftest.py` | (基建) | 零依赖内存 SQLite(asyncio.run + StaticPool)；最小 app + httpx ASGITransport(不触发 lifespan/APScheduler/Form 依赖) | 单事件循环内 seed+请求,避免跨循环;依赖覆盖 get_db |
| `tests/test_tracker_model.py` | 32 | 租赁效率/年化模型纯函数 | 常量自洽于 `期望周期=R+(1-S)×CD, 有效天=365/周期×R`：S=0(传统)/0.85(0CD)/1(完美转租)、CD=0/8；`_calc_annuals` rented_value=0/负/None、VIP vs 非VIP、0.7/0.3 综合权重、零收入;`_parse_stats_desc` 全角半角冒号/千分位/缺字段/空;`_safe_float/int` NaN/非法 |
| `tests/test_pricing_query.py` | 14 | `get_latest_prices` / `get_all_latest_prices` | 空名单、不存在饰品、跨平台取 min、**多分钟只认最新分钟(即便旧分钟更低)**、null/0/负价排除、最新分钟全无效则整条剔除、float 类型 |
| `tests/test_tracker_crud.py` | 19 | tracker CRUD/聚合/Excel | `get_monthly_summary` **VIP 10% vs 非VIP 20% 逐日动态费率**、缺天预估(日均×当月天数)、满月不预估、月末库存价值取最后正值;`update_record` 不存在→None/字段白名单/改核心字段重算年化/改成本重算涨跌;`get/set_config` 默认回退+upsert;Excel 导入跳空行+导出往返 |
| `tests/test_youpin_pagination.py` | 16 | `import_buy_records` / `import_sell_records` 分页 loop | 8 场景×2：空页、单页不满、满页+空、满页+不满、多满页+空、首页异常 break、次页异常保留首页、**MAX_PAGES(200) 防无限循环**;mock `fetch_*_records` |
| `tests/test_dashboard_api.py` | 15 | overview / chart-data (ASGI) | **ACTIVE_STATUSES 口径**(空库存/全 in_storage/全 sold/混合,in_storage·sold 不计)、effective_cost=coalesce(manual,purchase)、覆盖率;**PnL 逐件 snapshot vs effective_cost**、manual 覆盖、未覆盖(缺价或缺成本)排除、无覆盖→None、多件同名累加;chart-data 类型聚合/PnL 分桶/top_value 排序/gainers·losers/icon_url min/剔除非活跃 |
| `tests/test_routes_misc.py` | 13 | monitoring / inventory 路由 | monitoring status 行数反映 seed/freshness 决定 healthy/degraded;portfolio-history **非法 range→422**、范围过滤、升序;inventory missing-cost(仅 ACTIVE 无成本)、list 默认 ACTIVE 口径/显式状态/all/**非法状态回退 ACTIVE**;summary |
| `tests/test_youpin_parsers.py` | 30 | 悠悠记录解析纯函数 | `_parse_price`(分→元/缺失/非数)、`_parse_qty`(字段优先级/0/负/非int 回退1)、`_parse_date`(毫秒戳/优先级/缺失/非法)、`_parse_hash_name`、`_parse_abrade`(>0 校验/fallback) |

测试策略：**characterize 当前真实行为**（不臆测应然），全部内存库 + mock 外部，无任何真实网络 / 不连生产 DB。

## 2. 发现的真实 bug

**无确认 bug。** 所有目标行为均按当前实现 characterize 通过,因此无需 xfail。
以下为**观察项(非 bug,已记录未修)**,供你决定是否后续处理：

- **观察 1 — 弃用 API**：`app/services/youpin.py:878` 用 `datetime.utcfromtimestamp(...)`(Python 3.12+ 弃用,未来移除)。当前功能正常,仅 DeprecationWarning。建议改 `datetime.fromtimestamp(ms/1000, tz=timezone.utc)`。
- **观察 2 — 弃用参数**：`app/api/routes/monitoring.py:121` `Query(..., regex=...)`(Pydantic v2 弃用,应为 `pattern=`)。功能正常,仅警告。
- **观察 3 — PnL 平台口径不一致(设计差异,非 bug)**：`app/services/steam.py:get_inventory_with_prices` 的逐件盈亏只用 **BUFF** 价(`buff_price`),而 `dashboard.get_overview` / `chart-data` 的 PnL 用**跨平台最低价**(`get_latest_prices`)。两处口径不同属设计选择,若期望一致需对齐。

## 3. 分支与 review 方式

```
分支: auto/test-suite (worktree: /home/kingk/projects/cs2-overnight)
查看提交: git -C /home/kingk/projects/cs2-overnight log --oneline main..auto/test-suite
查看改动: git -C /home/kingk/projects/cs2-overnight diff main..auto/test-suite
跑测试:   cd /home/kingk/projects/cs2-overnight && python3 -m pytest -q
合并(由你决定): git checkout main && git merge auto/test-suite   # 仅新增 tests/ + 文档
```
所有改动均为**新增文件**(`tests/test_*.py`、`tests/conftest.py`、`PROGRESS.md`、`REPORT.md`),
未修改任何 `app/` 业务逻辑(`git diff main..auto/test-suite -- app/` 为空)。

## 4. 红线声明

- ✅ **未触碰线上 serve 文件**：所有工作在隔离 worktree 的 `auto/test-suite` 分支,未改 `static/`、未碰主仓 working tree。
- ✅ **未部署**：无 scp、无 git pull、无任何线上文件变更。
- ✅ **未重启服务 / 未动 nginx**：无 systemctl、无 reload。
- ✅ **未 push / 未动 main / 未动 remote**：仅本地 commit 到 `auto/test-suite`。
- ✅ **未碰外部世界 / 真实数据**：全部内存 SQLite + mock(SteamDT/Steam/悠悠/Telegram 均未调用),零真实网络请求,未连生产 DB。
