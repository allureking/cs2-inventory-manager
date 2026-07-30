"""
手滑低价防线（v0.13.4）

当人工输入的价格明显低于该件当前市价时，不直接放行、也不直接拒绝，而是回一个
可识别的 409，由前端弹二次确认、用户点确认后带 `confirm_below_market=true` 重发。

为什么是「二次确认」而不是「硬拦截」
------------------------------------
基准本身有已知的系统性偏差：`market_hash_name` 只区分磨损档位（如 Field-Tested）与
StatTrak/纪念品，**不区分档内 float、不区分图案**（蓝宝石、渐变、印花本）。同名两件
真实价值可以差数倍，所以一件档内成色差的货，合理定价本来就可能低于同名跨平台最低价。
用一个已知会偏的数去做硬拦截是错配；可点穿的确认才是与这种不确定性相称的强度。

为什么查不到基准时放行（fail-open）
------------------------------------
缺基准最集中的是「刚买入、当天还没进采价名单、第一次上架」的品——而这恰恰是最需要
能挂出去的场景。项目既有的态度也是如此：自动定价拿不到市价时明确把人推向手动定价
（youpin_listing.py 的「无法获取市场价格，请手动定价」），再用「没有市价」去拦手动
定价就自相矛盾了。何况这道防线没有安全属性，fail-closed 换不来任何保障，只换来不可用。
极端值另有硬闸兜底（listing.py 的 gt=0 / _MAX_PRICE / _MAX_RENT）。

基准来源
--------
- 售价：`pricing.get_latest_prices()`（本地 price_snapshot，每平台各取最新再跨平台取
  最低）。免 token、免 HTTP、生产实测覆盖 4282/4323 = 99.05% 的活跃持仓。
- 日租金：`price_snapshot` **没有租金列**，本地无任何市场租金来源，只能实时打悠悠
  `fetch_market_lease_price`。需要 token 与一次 HTTP；拿不到就放行。
  注意这里取 `min(units)` 而不是 `units[0]`：出租查询的请求体里**没有排序参数**
  （对比出售查询带了 `listSortType: "2"`），docstring 里那句「按租金升序」没有 payload
  支撑，`units[0]` 可能是任意一条挂单。
  也不用 `calc_lease_price()` 的返回值——那是「建议挂价」，含 ×0.97 之类的加工，
  拿它当基准会双重打折。同理售价侧不能用 `suggested_sell`（含 -0.01 undercut）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 触发二次确认的阈值：price < 基准 × LOW_PRICE_CONFIRM_RATIO。
# 0.95 = 「比市价低 5% 以上」。
# 若想改成只拦极端离谱价（例如「低到只剩市价的 5%」），把它调成 0.05 即可——
# 判据表达式不变，只是这一个常数的含义从「低 5%」变成「只剩 5%」。
LOW_PRICE_CONFIRM_RATIO = 0.95

# 409 响应里的机器可读标记，前端据此弹确认框（不要改动，前端在匹配它）
BELOW_MARKET_CODE = "below_market_price"

# 租金基准要打一次悠悠 HTTP。共享 client 的超时是 20s——那是拉数据的量级，
# 不能让一个"锦上添花"的基准查询把用户的改价对话框卡住 20 秒。
# 超过这个时间就当查不到（放行）。
LEASE_BASIS_TIMEOUT_S = 4.0


@dataclass(frozen=True)
class Basis:
    """一个价格基准。value 为 None 表示查不到基准（调用方应放行）。"""

    value: Optional[float]
    source: str          # 'snapshot' | 'youpin_lease' | 'none'
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.value is not None and self.value > 0


NO_BASIS = Basis(value=None, source="none", detail="无可用基准")


def is_below_market(price: Optional[float], basis: Basis) -> bool:
    """price 是否低到需要二次确认。基准不可用或价格为空 → False（放行）。"""
    if price is None or not basis.usable:
        return False
    return float(price) < basis.value * LOW_PRICE_CONFIRM_RATIO


async def sell_basis(db: AsyncSession, market_hash_name: Optional[str]) -> Basis:
    """售价基准 = 本地 price_snapshot 的跨平台最低价。"""
    if not market_hash_name:
        return NO_BASIS
    from app.services.pricing import get_latest_prices

    try:
        price_map = await get_latest_prices([market_hash_name], db)
    except Exception as e:  # 基准查询失败绝不能挡住改价
        logger.warning("price_guard: 售价基准查询失败 name=%s: %s", market_hash_name, e)
        return NO_BASIS

    px = price_map.get(market_hash_name)
    if not px or px <= 0:
        return NO_BASIS
    return Basis(value=float(px), source="snapshot", detail="本地快照·跨平台最低价")


async def lease_basis(template_id: Optional[int]) -> Basis:
    """日租金基准 = 悠悠市场挂租列表里的最低日租。无 token / 冷门品 → 无基准。"""
    if not template_id:
        return NO_BASIS
    from app.services.youpin import fetch_market_lease_price, get_active_token

    if not get_active_token():
        return NO_BASIS

    try:
        market_list = await asyncio.wait_for(
            fetch_market_lease_price(int(template_id)), timeout=LEASE_BASIS_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        logger.info("price_guard: 租金基准查询超时(%.1fs) template=%s，放行",
                    LEASE_BASIS_TIMEOUT_S, template_id)
        return NO_BASIS
    except Exception as e:  # 限流/token 失效都只是"拿不到基准"，不是错误
        logger.info("price_guard: 租金基准查询失败 template=%s: %s", template_id, e)
        return NO_BASIS

    units: list[float] = []
    for it in (market_list or [])[:20]:
        u = it.get("leaseUnitPrice") or it.get("LeaseUnitPrice")
        if u is None:
            continue
        try:
            u = float(u)
        except (TypeError, ValueError):
            continue
        if u > 0:
            units.append(u)

    if not units:
        return NO_BASIS
    # min 而非 [0]：出租查询没带排序参数，不能假定列表有序
    return Basis(value=min(units), source="youpin_lease", detail="悠悠市场·最低日租")


def below_market_detail(field: str, price: float, basis: Basis) -> dict:
    """构造 409 的 detail，前端据此渲染确认文案。"""
    pct_below = round((1 - float(price) / basis.value) * 100, 1)
    return {
        "code": BELOW_MARKET_CODE,
        "field": field,
        "price": round(float(price), 2),
        "basis": round(basis.value, 2),
        "basis_source": basis.source,
        "basis_detail": basis.detail,
        "pct_below": pct_below,
        "threshold_pct": round((1 - LOW_PRICE_CONFIRM_RATIO) * 100, 1),
        "message": (
            f"{field} ¥{float(price):.2f} 比{basis.detail} ¥{basis.value:.2f} "
            f"低 {pct_below}%，请确认不是手滑"
        ),
    }
