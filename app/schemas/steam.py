"""Steam Community 库存接口响应 Pydantic 模型"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class SteamAsset(BaseModel):
    """assets 数组中的单条记录"""
    appid: int
    contextid: str
    assetid: str
    classid: str
    instanceid: str
    amount: str = "1"


class SteamDescription(BaseModel):
    """descriptions 数组中的单条记录"""
    classid: str
    instanceid: str
    name: str
    market_hash_name: str
    type: Optional[str] = None
    icon_url: Optional[str] = None
    tradable: int = 0
    marketable: int = 0


class SteamInventoryResponse(BaseModel):
    """Steam Community 库存接口完整响应"""
    assets: List[SteamAsset] = Field(default_factory=list)
    descriptions: List[SteamDescription] = Field(default_factory=list)
    total_inventory_count: int = 0
    more_items: Optional[int] = None
    last_assetid: Optional[str] = None
    success: int = 1


class InventoryItemOut(BaseModel):
    """库存列表接口返回的单条物品（含价格）"""
    asset_id: str
    market_hash_name: str
    name: str
    item_type: Optional[str]
    icon_url: Optional[str]
    tradable: bool
    marketable: bool
    in_inventory: bool
    purchase_price: Optional[float]
    purchase_platform: Optional[str]

    # 来自 price_snapshot 的实时价格（可能为空，表示尚未采集）
    buff_sell_price: Optional[float] = None
    youpin_sell_price: Optional[float] = None
    steam_sell_price: Optional[float] = None
    snapshot_minute: Optional[str] = None

    # 盈亏（仅当 purchase_price 和价格都有值时计算）
    profit_loss: Optional[float] = None
    profit_pct: Optional[float] = None
