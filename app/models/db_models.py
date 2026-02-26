"""
数据库 ORM 模型

表设计：
  item             — CS2 饰品基础信息（来自 /base 接口，每天同步一次）
  price_snapshot   — 各平台实时价格快照（来自 /price/single 或 /price/batch）
  item_avg_price   — 各平台近 N 天均价（来自 /price/avg）
  inventory_item   — 我的全持仓（主动投资/租赁物品）
  storage_unit     — 储物柜状态追踪（通过 instance_id 变化检测存取事件）

status 状态机（inventory_item.status）：
  in_steam    → 当前在 Steam 可见库存（可交易/可租）
  in_storage  → 已存入储物柜（个人收藏，不计入持仓价值）
  rented_out  → 从 Steam 消失且储物柜无变化，推断为出租中（仍属于我）
  sold        → Phase 3 出售记录确认已售出
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
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
    # CSQAQ 饰品 ID（用于调用 CSQAQ 数据 API）
    csqaq_good_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
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


class InventoryItem(Base):
    """
    我的 CS2 全持仓（含出租中饰品）。

    status 状态机：
      in_steam   → 当前在 Steam 库存（最新一次同步可见）
      rented_out → 从 Steam 消失且无出售记录，推断为出租中（仍属于我）
      sold       → Phase 3 出售记录确认已售出

    指纹追踪：
      用 class_id + instance_id 识别同一件物品。
      出租归还后 asset_id 会变，但 class_id+instance_id 不变，
      同步时通过指纹匹配来更新 asset_id 而非创建新记录。
    """

    __tablename__ = "inventory_item"
    __table_args__ = (
        # 同一用户下 class_id+instance_id 的联合索引（用于指纹匹配）
        UniqueConstraint("steam_id", "class_id", "instance_id", name="uq_item_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    steam_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    # Steam 资产标识（asset_id 在物品转移后会变，仅代表最近一次在 Steam 的 ID）
    asset_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    class_id: Mapped[str] = mapped_column(String, nullable=False)
    instance_id: Mapped[str] = mapped_column(String, nullable=False)

    # 物品信息
    market_hash_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    icon_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tradable: Mapped[bool] = mapped_column(Boolean, default=True)
    marketable: Mapped[bool] = mapped_column(Boolean, default=True)

    # 状态：in_steam | in_storage | rented_out | sold
    status: Mapped[str] = mapped_column(String(16), default="in_steam", index=True, nullable=False)

    # 时间线
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_in_steam_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    left_steam_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 悠悠有品租赁标识（Youpin 来源物品，class_id="YOUPIN", instance_id=str(commodity_id)）
    youpin_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    youpin_commodity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # 磨损值（用于精确匹配买入记录，0.0 ~ 1.0，无磨损物品为 None）
    abrade: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 悠悠有品模板 ID（物品类型 ID，用于查询市场价格）
    youpin_template_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # 成本（Phase 3）
    purchase_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    purchase_price_manual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    purchase_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    purchase_platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # 目标收益率 %（达标即卖，为 None 时使用全局默认值）
    target_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class PriceHistory(Base):
    """每日价格 OHLC 记录（量化分析时序基础）"""

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("market_hash_name", "platform", "record_date", name="uq_price_history"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # BUFF163 / 悠悠有品 / C5 / ALL

    open_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    sell_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    bidding_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    record_date: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # "20260222"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QuantSignal(Base):
    """饰品量化信号（每日计算后覆盖写入）"""

    __tablename__ = "quant_signal"
    __table_args__ = (
        UniqueConstraint("market_hash_name", "signal_date", name="uq_quant_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    signal_date: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    # 技术指标
    rsi_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_position: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # %B
    bb_width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    momentum_7: Mapped[Optional[float]] = mapped_column(Float, nullable=True)    # 7 天动量 %
    momentum_30: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 30 天动量 %
    volatility_30: Mapped[Optional[float]] = mapped_column(Float, nullable=True) # 年化波动率
    ma_7: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ma_30: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ath_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ath_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # 当前 / ATH %

    # 跨平台价差
    spread_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 新增维度指标
    annualized_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 年化收益率 %
    holding_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)       # 持有件数
    concentration_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 持仓市值占比 %
    market_share_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)    # 持仓/市场在售 %
    volatility_zscore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 波动率 z-score（vs 同类）

    # CSQAQ 数据（每日同步）
    daily_rent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)      # 悠悠有品短租日租金
    rental_annual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 短租年化收益率 %
    steam_turnover: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Steam 日均成交量
    global_supply: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # 全球存世量

    # 综合评分 0-100
    sell_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opportunity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QuantAlert(Base):
    """量化预警记录"""

    __tablename__ = "quant_alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PortfolioSnapshot(Base):
    """定时记录的投资组合快照（用于组合价值趋势图）"""

    __tablename__ = "portfolio_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 时间戳（精确到分钟，格式 YYYYMMDDHHmm）
    snapshot_minute: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)

    # 持仓数量
    total_active: Mapped[int] = mapped_column(Integer, default=0)
    in_steam_count: Mapped[int] = mapped_column(Integer, default=0)
    rented_out_count: Mapped[int] = mapped_column(Integer, default=0)
    in_storage_count: Mapped[int] = mapped_column(Integer, default=0)

    # 价值（¥）
    total_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    in_steam_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rented_out_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 市价覆盖率
    market_priced_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_priced_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StorageUnit(Base):
    """
    储物柜状态追踪表。

    每次同步时更新各储物柜的 instance_id。
    instance_id 发生变化 → 储物柜内容有变动（有物品存入或取出）。
    结合同次同步中消失/出现的物品，推断物品的存取行为：
      物品消失 + 储物柜变化 → 该物品存入储物柜 (in_storage)
      物品出现 + 储物柜变化 → 从储物柜取出，进入 in_steam（可录入购入价）
      物品消失 + 储物柜无变化 → 租出或交易走了 (rented_out)
    """

    __tablename__ = "storage_unit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    steam_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    asset_id: Mapped[str] = mapped_column(String, index=True, nullable=False)   # 储物柜容器当前 asset_id
    class_id: Mapped[str] = mapped_column(String, nullable=False)               # 固定 3604678661
    instance_id: Mapped[str] = mapped_column(String, nullable=False)            # 内容变化时此值改变
    prev_instance_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # 上次的 instance_id

    # 是否在本次同步中检测到内容变化
    changed_in_last_sync: Mapped[bool] = mapped_column(Boolean, default=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
