# CLAUDE.md — cs2-inventory-manager 协作约定

## 测试纪律
- 任何改动 app/ 的代码后，提交 / 合并 / 部署前必须 `python3 -m pytest -q` 通过。
- tests/ 是回归网。测试由绿变红时，先确认是不是碰坏了被钉住的核心行为：租赁模型（期望周期=R+(1-S)×CD）、pricing 取值、逐件 PnL（VIP10%/非VIP20%、manual 覆盖）、youpin 分页 loop-until-empty、ACTIVE_STATUSES 口径。
- 若红是因为「有意的行为变更」（如修 utcfromtimestamp / Query(regex=) / DISTINCT ON 等 deprecation，或调整 steam BUFF 口径），把对应 characterization 测试更新到新行为，不要为了让它过而删断言或注释掉测试。
- 覆盖率口径：核心业务逻辑追求高分支覆盖；外部 IO（HTTP 客户端 / RSA-AES / 调度）的低覆盖在 REPORT.md §3 已声明「故意不覆盖」，不必为数字硬凑。

## pre-commit 拦截
- 本仓库配了 pre-commit hook，`git commit` 前自动跑 `python3 -m pytest -q`，失败则挡下提交（实现见 `.pre-commit-config.yaml`）。
- 新克隆仓库后需启用一次：`pip install pre-commit && pre-commit install`。
