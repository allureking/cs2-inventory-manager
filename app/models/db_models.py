"""
数据库 ORM 模型

表设计：
  item             — CS2 饰品基础信息（来自 /base 接口，每天同步一次）
  price_snapshot   — 各平台实时价格快照（来自 /price/single 或 /price/batch）
  item_avg_price   — 各平台近 N 天均价（来自 /price/avg）
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Item(Base):
    """CS2 饰品基础信息表（每天通过 /base 接口全量同步）"""

    __tablename__ = "item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)  # 中文名
    # 各平台 item_id，逗号分隔存 JSON 字符串（简单场景够用，复杂可拆表）
    platform_ids_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PriceSnapshot(Base):
    """各平台实时价格快照（每次查询后写入）"""

    __tablename__ = "price_snapshot"
    __table_args__ = (
        # 同一饰品 + 同一平台 + 同一分钟只保留一条（避免频繁写入膨胀）
        UniqueConstraint("market_hash_name", "platform", "snapshot_minute", name="uq_price_snapshot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_item_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    sell_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    bidding_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bidding_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # API 返回的原始更新时间（Unix 时间戳，秒）
    api_update_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # 本地写入时间（精确到分钟，用于去重）
    snapshot_minute: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "202502211435"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ItemAvgPrice(Base):
    """饰品近 N 天均价（来自 /price/avg 接口）"""

    __tablename__ = "item_avg_price"
    __table_args__ = (
        UniqueConstraint("market_hash_name", "platform", "days", "record_date", name="uq_avg_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # "ALL" 代表跨平台均值
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    avg_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    record_date: Mapped[str] = mapped_column(String(8), nullable=False)  # e.g. "20250221"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
