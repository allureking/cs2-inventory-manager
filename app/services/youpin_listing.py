"""
悠悠有品 自动上架/改价/下架 服务

支持：
  出售上架：按市场参考价自动定价（低一分策略 / 止盈率覆盖）
  出租上架：按市场参考租价自动定价（均价折扣 / 按售价比例）
  可租可售：同时设置出售价和出租价
  改价：按 CommodityId 修改已上架物品价格
  下架：按 CommodityId 下架

定价算法（源自 Steamauto 实战逻辑）：
  出售：取市场前10条价格，差距<5% → 跟最低，差距≥5% → 取第二低
        可叠加止盈率覆盖（price ≥ buy_price × (1 + ratio)）
        可开启低一分策略（最终价格 -0.01）
  出租：市场均价 × 0.97，不低于当前最低价
        长租价 = min(短租 × 0.98, 均长租 × 0.95)
        可按售价固定比例设租金
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.services.youpin import (
    YOUPIN_API,
    TokenExpiredError,
    _check,
    _data,
    _headers,
    fetch_market_lease_price,
    fetch_market_sell_price,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  定价算法
# ══════════════════════════════════════════════════════════════

def calc_sell_price(
    market_list: list[dict],
    buy_price: float = 0.0,
    take_profit_ratio: float = 0.0,
    use_undercut: bool = True,
    min_price: float = 0.01,
) -> Optional[float]:
    """
    计算出售价格。
    market_list: fetch_market_sell_price() 返回的挂单列表
    buy_price: 购入价（元），>0 时启用止盈率保护
    take_profit_ratio: 止盈率，如 0.1 = 10%，0 = 不启用
    use_undercut: True = 最终价格 -0.01（低一分抢单）
    """
    prices = []
    for item in market_list[:10]:
        p = item.get("price") or item.get("Price") or item.get("sellPrice")
        if p:
            try:
                prices.append(float(p))
            except (TypeError, ValueError):
                pass

    if not prices:
        return None

    prices.sort()

    if len(prices) == 1:
        sale_price = prices[0]
    elif prices[1] < prices[0] * 1.05:
        # 前两档差距 < 5%，跟最低价
        sale_price = prices[0]
    else:
        # 差距 >= 5%，取第二低（避免追单价位孤立的极低价）
        sale_price = prices[1]

    # 止盈率保护：不低于 buy_price × (1 + ratio)
    if buy_price > 0 and take_profit_ratio > 0:
        floor = round(buy_price * (1 + take_profit_ratio), 2)
        sale_price = max(sale_price, floor)

    # 低一分策略
    if use_undercut and sale_price > min_price + 0.01:
        sale_price = round(sale_price - 0.01, 2)

    return max(round(sale_price, 2), min_price)


def calc_lease_price(
    market_list: list[dict],
    sell_price: float = 0.0,
    fix_lease_ratio: float = 0.0,
    min_unit: float = 0.01,
) -> Optional[dict]:
    """
    计算出租价格（短租/长租/押金）。
    market_list: fetch_market_lease_price() 返回的挂租列表
    sell_price: 出售市价（元），用于按比例设租金
    fix_lease_ratio: 按售价固定日租金比例，如 0.01 = 1%/天，0 = 不启用

    返回 {"lease_unit": float, "long_lease_unit": float, "deposit": float}
    """
    if not market_list:
        return None

    units, long_units, deposits = [], [], []
    for item in market_list[:10]:
        u = item.get("leaseUnitPrice") or item.get("LeaseUnitPrice")
        l_ = item.get("longLeaseUnitPrice") or item.get("LongLeaseUnitPrice")
        d = item.get("leaseDeposit") or item.get("LeaseDeposit")
        if u:
            try:
                units.append(float(u))
            except (TypeError, ValueError):
                pass
        if l_:
            try:
                long_units.append(float(l_))
            except (TypeError, ValueError):
                pass
        if d:
            try:
                deposits.append(float(d))
            except (TypeError, ValueError):
                pass

    if not units:
        return None

    avg_unit = sum(units) / len(units)
    lease_unit = max(avg_unit * 0.97, units[0], min_unit)

    if long_units:
        avg_long = sum(long_units) / len(long_units)
        long_unit = min(lease_unit * 0.98, avg_long * 0.95)
        long_unit = max(long_unit, long_units[0], min_unit)
    else:
        long_unit = max(lease_unit - 0.01, min_unit)

    if deposits:
        avg_dep = sum(deposits) / len(deposits)
        deposit = max(avg_dep * 0.98, min(deposits))
    else:
        deposit = round(sell_price * 0.3, 2) if sell_price > 0 else 100.0

    # 按售价固定比例覆盖（取较大值）
    if fix_lease_ratio > 0 and sell_price > 0:
        ratio_unit = round(sell_price * fix_lease_ratio, 2)
        lease_unit = max(lease_unit, ratio_unit)
        long_unit = max(long_unit, lease_unit * 0.98)

    return {
        "lease_unit": round(lease_unit, 2),
        "long_lease_unit": round(min(long_unit, lease_unit), 2),
        "deposit": round(deposit, 2),
    }


# ══════════════════════════════════════════════════════════════
#  上架 / 改价 / 下架
# ══════════════════════════════════════════════════════════════

async def list_for_sell(
    asset_id: str,
    price: float,
) -> dict:
    """
    将物品上架出售（仅出售，不出租）。
    asset_id: Steam asset_id（SellInventoryWithLeaseV2 用 AssetId）
    price: 出售价（元）
    """
    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/commodity/Inventory/SellInventoryWithLeaseV2",
            headers=_headers(),
            json={
                "GameId": "730",
                "ItemInfos": [{
                    "AssetId": asset_id,
                    "IsCanLease": False,
                    "IsCanSold": True,
                    "Price": price,
                    "Remark": "",
                }],
            },
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "list_for_sell")
    return {"ok": True, "asset_id": asset_id, "price": price}


async def list_for_lease(
    asset_id: str,
    lease_unit: float,
    long_lease_unit: float,
    deposit: float,
    max_days: int = 30,
) -> dict:
    """
    将物品上架出租（仅出租，不出售）。
    """
    item_info: dict = {
        "AssetId": asset_id,
        "IsCanLease": True,
        "IsCanSold": False,
        "LeaseDeposit": str(deposit),
        "LeaseMaxDays": max_days,
        "LeaseUnitPrice": lease_unit,
        "CompensationType": 0,
    }
    if max_days > 8:
        item_info["LongLeaseUnitPrice"] = long_lease_unit

    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/commodity/Inventory/SellInventoryWithLeaseV2",
            headers=_headers(),
            json={"GameId": "730", "ItemInfos": [item_info]},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "list_for_lease")
    return {"ok": True, "asset_id": asset_id, "lease_unit": lease_unit, "deposit": deposit}


async def list_for_both(
    asset_id: str,
    sell_price: float,
    lease_unit: float,
    long_lease_unit: float,
    deposit: float,
    max_days: int = 30,
) -> dict:
    """
    可租可售同时上架（IsCanLease=True, IsCanSold=True）。
    """
    item_info: dict = {
        "AssetId": asset_id,
        "IsCanLease": True,
        "IsCanSold": True,
        "Price": sell_price,
        "LeaseDeposit": str(deposit),
        "LeaseMaxDays": max_days,
        "LeaseUnitPrice": lease_unit,
        "CompensationType": 0,
    }
    if max_days > 8:
        item_info["LongLeaseUnitPrice"] = long_lease_unit

    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/commodity/Inventory/SellInventoryWithLeaseV2",
            headers=_headers(),
            json={"GameId": "730", "ItemInfos": [item_info]},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "list_for_both")
    return {"ok": True, "asset_id": asset_id, "sell_price": sell_price,
            "lease_unit": lease_unit, "deposit": deposit}


async def change_price(
    commodity_id: int,
    sell_price: Optional[float] = None,
    lease_unit: Optional[float] = None,
    long_lease_unit: Optional[float] = None,
    deposit: Optional[float] = None,
    is_can_sold: bool = True,
    is_can_lease: bool = False,
) -> dict:
    """
    修改已上架物品价格（使用 CommodityId，非 AssetId）。
    改价接口：PUT PriceChangeWithLeaseV2
    """
    commodity_info: dict = {
        "CommodityId": commodity_id,
        "IsCanSold": is_can_sold,
        "IsCanLease": is_can_lease,
    }
    if sell_price is not None and is_can_sold:
        commodity_info["Price"] = sell_price
    if is_can_lease and lease_unit is not None:
        commodity_info["LeaseUnitPrice"] = lease_unit
        if long_lease_unit is not None:
            commodity_info["LongLeaseUnitPrice"] = long_lease_unit
        if deposit is not None:
            commodity_info["LeaseDeposit"] = str(deposit)

    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.put(
            f"{YOUPIN_API}/api/commodity/Commodity/PriceChangeWithLeaseV2",
            headers=_headers(),
            json={"Commoditys": [commodity_info]},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "change_price")
    return {"ok": True, "commodity_id": commodity_id, "sell_price": sell_price}


async def delist_item(commodity_id: int) -> dict:
    """下架物品（出售和出租通用）"""
    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.put(
            f"{YOUPIN_API}/api/commodity/Commodity/OffShelf",
            headers=_headers(),
            json={"CommodityId": commodity_id},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "delist_item")
    return {"ok": True, "commodity_id": commodity_id}


# ══════════════════════════════════════════════════════════════
#  货架查询
# ══════════════════════════════════════════════════════════════

def _normalize_shelf_item(item: dict) -> dict:
    """将悠悠货架 API 原始字段统一映射为前端通用字段名"""
    return {
        "commodityId": item.get("id"),
        "templateId": item.get("templateId"),
        "name": item.get("name"),
        "commodityHashName": item.get("commodityHashName"),
        "abrade": item.get("abrade"),
        "imgUrl": item.get("imgUrl"),
        # 出售
        "price": item.get("sellAmount"),
        # 出租
        "leaseUnitPrice": item.get("shortLeaseAmount"),
        "longLeasePrice": item.get("longLeaseAmount"),
        "leaseDeposit": item.get("depositAmount"),
        "leaseAmountDesc": item.get("leaseAmountDesc"),
        "depositAmountDesc": item.get("depositAmountDesc"),
        "leaseMaxDays": item.get("leaseMaxDays"),
        "leaseMaxDaysDesc": item.get("leaseMaxDaysDesc"),
        "openSublet": item.get("openSublet"),   # 是否开启转租
        "steamAssetId": item.get("steamAssetId"),
        "status": item.get("status"),
        "canLease": item.get("canLease"),
        "canSell": item.get("commodityCanSell"),
    }


async def get_sell_shelf(page: int = 1, page_size: int = 50) -> dict:
    """获取当前出售货架列表"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/new/commodity/v1/commodity/list/sell",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": "730"},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "sell_shelf")
    data = _data(body)
    if isinstance(data, dict):
        raw = (data.get("commodityInfoList") or data.get("commodityList") or
               data.get("list") or [])
        stats = data.get("statisticalData") or {}
        total = stats.get("quantity") or data.get("totalCount") or len(raw)
        return {"items": [_normalize_shelf_item(i) for i in raw], "total": total, "stats": stats}
    return {"items": [], "total": 0, "stats": {}}


async def get_lease_shelf(page: int = 1, page_size: int = 50) -> dict:
    """获取当前出租货架列表"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/new/commodity/v1/commodity/list/lease",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": "730"},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "lease_shelf")
    data = _data(body)
    if isinstance(data, dict):
        raw = (data.get("commodityInfoList") or data.get("commodityList") or
               data.get("list") or [])
        stats = data.get("statisticalData") or {}
        total = stats.get("quantity") or data.get("totalCount") or len(raw)
        return {"items": [_normalize_shelf_item(i) for i in raw], "total": total, "stats": stats}
    return {"items": [], "total": 0, "stats": {}}


# ══════════════════════════════════════════════════════════════
#  一键智能上架（查价 + 定价 + 上架）
# ══════════════════════════════════════════════════════════════

async def smart_list(
    asset_id: str,
    template_id: int,
    abrade: Optional[float],
    mode: str = "sell",          # "sell" | "lease" | "both"
    buy_price: float = 0.0,
    take_profit_ratio: float = 0.0,
    fix_lease_ratio: float = 0.0,
    use_undercut: bool = True,
) -> dict:
    """
    一键智能上架：自动查询市场价 → 计算定价 → 上架。
    mode:
      "sell"  → 仅出售
      "lease" → 仅出租
      "both"  → 可租可售
    返回上架结果 + 计算出的价格
    """
    sell_price = None
    lease_info = None

    if mode in ("sell", "both"):
        market_sell = await fetch_market_sell_price(template_id, abrade)
        sell_price = calc_sell_price(
            market_sell,
            buy_price=buy_price,
            take_profit_ratio=take_profit_ratio,
            use_undercut=use_undercut,
        )

    if mode in ("lease", "both"):
        market_lease = await fetch_market_lease_price(template_id)
        lease_info = calc_lease_price(
            market_lease,
            sell_price=sell_price or 0.0,
            fix_lease_ratio=fix_lease_ratio,
        )

    if mode == "sell":
        if sell_price is None:
            return {"ok": False, "error": "无法获取市场价格，请手动定价"}
        result = await list_for_sell(asset_id, sell_price)

    elif mode == "lease":
        if lease_info is None:
            return {"ok": False, "error": "无法获取市场租价，请手动定价"}
        result = await list_for_lease(
            asset_id,
            lease_info["lease_unit"],
            lease_info["long_lease_unit"],
            lease_info["deposit"],
        )

    else:  # both
        if sell_price is None or lease_info is None:
            return {"ok": False, "error": "无法获取市场价格，请手动定价"}
        result = await list_for_both(
            asset_id, sell_price,
            lease_info["lease_unit"],
            lease_info["long_lease_unit"],
            lease_info["deposit"],
        )

    return {
        **result,
        "sell_price": sell_price,
        "lease_info": lease_info,
    }
