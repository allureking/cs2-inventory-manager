# CS2 Inventory Manager

CS2 饰品量化交易监控系统 — 集库存管理、实时市价追踪、盈亏分析、量化信号与自动化运维于一体。

## 功能概览

### 库存管理
- Steam 库存自动同步（支持 7 天交易保护期物品）
- 储物柜追踪：通过 instance_id 变化自动检测存取事件
- 悠悠有品集成：租赁导入、库存导入、买入记录精确匹配（RSA+AES 加密通信）
- 物品状态机：`in_steam` → `rented_out` → `sold`

### 实时定价
- 双数据源：SteamDT Open API + 悠悠有品官方市价
- 每 30 分钟自动采集全量市价
- 跨平台最低价聚合
- 支持手动定价覆盖

### 盈亏分析
- 逐件盈亏计算（成本 vs 市价）
- 组合价值快照：每 30 分钟自动记录持仓总值、成本、PnL
- 组合价值走势图（支持 24h / 7d / 30d / 90d 时间范围）

### 量化信号
- 技术指标：RSI(14)、布林带（%B / Width）、7/30 天动量、年化波动率
- 综合评分：卖出评分 + 机会评分（0-100）
- 预警系统：自动生成交易提醒
- 套利雷达：跨平台价差检测与排名
- 日线 OHLC 聚合 + 历史数据回填

### 上架管理
- 悠悠有品货架管理：出售 / 出租 / 转租
- 批量智能改价（自动跟价策略）
- 一键上架 / 下架 / 改价

### 监控与运维
- 看门狗脚本：每 5 分钟健康检查，异常自动重启
- SQLite 热备份：每 6 小时自动备份，保留 30 份
- 数据库完整性检查、磁盘空间监控
- 系统状态 API：运行时间、数据新鲜度、采集器状态

### 前端
- 单页应用（Alpine.js + Tailwind CSS + Chart.js）
- 深色 / 浅色主题切换
- 中文 / English 全局语言切换
- 涨跌色模式切换（A 股红涨绿跌 / 美股绿涨红跌）
- 网站内置双语更新日志

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · Uvicorn |
| 数据库 | SQLite（aiosqlite）· SQLAlchemy 2.0 |
| 定时任务 | APScheduler（AsyncIO） |
| 前端 | Alpine.js · Tailwind CSS · Chart.js |
| 加密 | PyCryptodome（RSA + AES，悠悠有品 API 通信） |
| 部署 | systemd · Cron · Nginx 反向代理 |

## 项目结构

```
cs2-inventory-manager/
├── main.py                        # FastAPI 应用入口 + APScheduler 定时任务
├── requirements.txt               # Python 依赖
├── .env.example                   # 环境变量模板
├── CHANGELOG.md                   # 更新日志
├── static/
│   └── index.html                 # SPA 前端（单文件）
├── tools/
│   ├── backup.sh                  # SQLite 热备份脚本
│   └── monitor.sh                 # 看门狗监控脚本
└── app/
    ├── core/
    │   ├── config.py              # 配置管理（Pydantic Settings）
    │   └── database.py            # 数据库引擎（SQLAlchemy async）
    ├── models/
    │   └── db_models.py           # 8 张表的 ORM 模型
    ├── schemas/
    │   ├── steamdt.py             # SteamDT 响应模型
    │   └── steam.py               # Steam API 响应模型
    ├── services/
    │   ├── steamdt.py             # SteamDT API 客户端
    │   ├── steam.py               # Steam 库存同步
    │   ├── youpin.py              # 悠悠有品 API（RSA/AES 加密）
    │   ├── youpin_listing.py      # 上架管理
    │   ├── quant_engine.py        # 量化指标计算引擎
    │   └── collector.py           # 后台采集任务
    └── api/routes/
        ├── prices.py              # 价格查询
        ├── items.py               # 物品目录
        ├── inventory.py           # 库存同步与成本管理
        ├── youpin.py              # 悠悠有品导入与同步
        ├── listing.py             # 上架管理
        ├── dashboard.py           # 仪表盘数据聚合
        ├── analysis.py            # 量化分析
        └── monitoring.py          # 系统监控
```

## 快速开始

### 1. 克隆与安装

```bash
git clone git@github.com:allureking/cs2-inventory-manager.git
cd cs2-inventory-manager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key 和凭证
```

需要的凭证：
- **SteamDT API Key** — 在 [SteamDT 开放平台](https://doc.steamdt.com) 申请
- **Steam Web API Key** — 在 [Steam API Key 页面](https://steamcommunity.com/dev/apikey) 获取
- **Steam 登录 Cookie** — 浏览器 F12 获取 `steamLoginSecure` + `sessionid`
- **悠悠有品 Token** — 在系统 Web 界面中通过短信登录获取

### 3. 启动服务

```bash
# 开发模式
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 生产部署（systemd）
sudo cp cs2-inventory.service /etc/systemd/system/
sudo systemctl enable --now cs2-inventory
```

### 4. 配置监控

```bash
chmod +x tools/monitor.sh tools/backup.sh

# 添加 cron 定时任务
crontab -e
# */5 * * * * /path/to/tools/monitor.sh >> /var/log/cs2-monitor.log 2>&1
# 0 */6 * * * /path/to/tools/backup.sh >> /var/log/cs2-backup.log 2>&1
```

## 定时任务

| 任务 | 频率 | 说明 |
|------|------|------|
| `collect_prices` | 每 30 分钟 | 采集全量市价 |
| `snapshot_portfolio` | 每 30 分钟 | 记录组合价值快照 |
| `aggregate_daily` | 每日 00:05 UTC | 日线 OHLC 聚合 |
| `compute_signals` | 每日 00:10 UTC | 量化信号计算 |
| `cleanup_snapshots` | 每日 01:00 UTC | 清理过期快照 |
| `backup.sh` | 每 6 小时 | SQLite 热备份 |
| `monitor.sh` | 每 5 分钟 | 健康检查 + 异常自动重启 |

## API 接口

| 模块 | 路径前缀 | 说明 |
|------|----------|------|
| 仪表盘 | `/api/dashboard` | 资产概览、持仓列表、市价刷新 |
| 量化分析 | `/api/analysis` | 信号、预警、套利、图表数据 |
| 系统监控 | `/api/monitoring` | 运行状态、组合历史、数据新鲜度 |
| 库存管理 | `/api/inventory` | Steam 同步、成本管理 |
| 悠悠有品 | `/api/youpin` | 导入、市价查询、登录 |
| 上架管理 | `/api/listing` | 上架、下架、改价 |
| 价格查询 | `/api/prices` | SteamDT 价格接口 |
