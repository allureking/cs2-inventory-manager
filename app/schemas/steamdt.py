"""SteamDT API 响应的 Pydantic 模型"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------- 通用响应包装 ----------

class SteamDTResponse(BaseModel):
    success: bool
    error_code: int = Field(alias="errorCode", default=0)
    error_msg: Optional[str] = Field(alias="errorMsg", default=None)
    error_code_str: Optional[str] = Field(alias="errorCodeStr", default=None)
    data: Any = None

    model_config = {"populate_by_name": True}


# ---------- /price/single & /price/batch ----------

class PlatformPriceVO(BaseModel):
    platform: str
    platform_item_id: Optional[str] = Field(alias="platformItemId", default=None)
    sell_price: Optional[float] = Field(alias="sellPrice", default=None)
    sell_count: Optional[int] = Field(alias="sellCount", default=None)
    bidding_price: Optional[float] = Field(alias="biddingPrice", default=None)
    bidding_count: Optional[int] = Field(alias="biddingCount", default=None)
    update_time: Optional[int] = Field(alias="updateTime", default=None)

    model_config = {"populate_by_name": True}


class BatchPlatformPriceVO(BaseModel):
    market_hash_name: str = Field(alias="marketHashName")
    data_list: list[PlatformPriceVO] = Field(alias="dataList", default_factory=list)

    model_config = {"populate_by_name": True}


# ---------- /price/avg ----------

class PlatformAvgPriceVO(BaseModel):
    platform: str
    avg_price: Optional[float] = Field(alias="avgPrice", default=None)

    model_config = {"populate_by_name": True}


class AveragePriceVO(BaseModel):
    market_hash_name: str = Field(alias="marketHashName")
    avg_price: Optional[float] = Field(alias="avgPrice", default=None)
    data_list: list[PlatformAvgPriceVO] = Field(alias="dataList", default_factory=list)

    model_config = {"populate_by_name": True}


# ---------- /base ----------

class PlatformBaseInfoVO(BaseModel):
    name: str
    item_id: Optional[str] = Field(alias="itemId", default=None)

    model_config = {"populate_by_name": True}


class BaseInfoVO(BaseModel):
    name: str
    market_hash_name: str = Field(alias="marketHashName")
    platform_list: list[PlatformBaseInfoVO] = Field(alias="platformList", default_factory=list)

    model_config = {"populate_by_name": True}
