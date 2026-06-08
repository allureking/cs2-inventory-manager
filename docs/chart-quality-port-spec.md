# 任务：重做数据可视化 —— 分析深度 + KOL 级美观（CC 有设计自主权）

> 目标只有两个：**更深的数据分析** + **更美观**。以另一个项目（KOL Dashboard）的图表为美学标杆，并**根据本项目（CS2 饰品库存/交易）自己的数据，增加更有洞察力的图表类型**（扇形/树状/分布/热力图等）。
>
> **加什么图、用什么类型、是否新增——由你（CC）评判**，前提是真能提升分析价值与观感。你有设计自主权，但要：① 先盘点真实数据再提案；② 非破坏式做 demo 给用户挑；③ 不动数据计算/接口逻辑。
>
> 你对源项目（KOL）无访问权，其视觉技法已全部提炼进 §4。

---

## 0. 交付方式：两个并排 demo 供对比（非破坏式）

不要直接改生产主应用。先产出**两个独立 demo**，让用户对比后选方向：

- **Demo A —「深色精修」**：保留 cs2 深色 slate 基底与现有布局，把 KOL 的图表视觉技法（§4）+ 新增图型（§2）套上去。改动克制、风险低。
- **Demo B —「KOL 全套重做」**：放开手整体向 KOL 看齐——引入 KOL 液态玻璃设计系统（§A：玻璃卡片、圆角、配色 token）、**重做主题系统**、KOL 同款统计卡与布局 + 同样的图表技法与新增图型。即「如果 cs2 长得像 KOL 会怎样」。

> **关于主题**：cs2 现有的浅色（给 `<html>` 加 `.light`）做得很烂、**可以丢，两个 demo 都不必保留它**：
> - Demo A：可只保留深色，或顺手把浅色修好；
> - Demo B：**直接用 KOL 的主题系统重做**（`data-theme` 亮色优先 + 暗色 + 跟随系统三态，见 §A.3），替换 `.light` hack。

两个 demo 都建成独立文件（`static/chart-lab-a.html` / `chart-lab-b.html`，或 `?lab=a` / `?lab=b`），调**现有后端真实数据**，给用户 **路径 + 截图**。用户选定后再合入主应用。

公共部分（两个 demo 都用）：§2 数据盘点与图表提案、§3 颜色源、§4 图表视觉工具箱、§5 工程层。差异只在「外壳」：A 用现有深色 slate 外壳，B 用 §A 的 KOL 液态玻璃外壳 + 重做主题。

**硬约束**：只改呈现层；不改数据计算/聚合/接口；新增图表只是对现有数据的新视图，不新增写操作。

---

## 1. 现状盘点（技术栈与锚点）

栈：**Alpine.js 3.14 + Tailwind（darkMode:'class'）+ Chart.js 4.4.0 + ApexCharts 3.54**。
- 两套图表引擎**都已加载，无需装新依赖**：
  - **Chart.js** → 做 KOL 风的折线/面积/圆角柱/环形（§4 工具箱主用）。
  - **ApexCharts** → 做 Chart.js 不擅长的类型：**treemap 树状图、heatmap 热力图、radialBar、candlestick** 等，原生支持。
- 主题**暗色优先**：`this.theme` 默认 `'dark'`（`static/app.js:331`），浅色时给 `<html>` 加 `.light`（`app.js:475/1718`）；判定 `_isDark = () => !document.documentElement.classList.contains('light')`。

现有三个图表（升级对象）：

| 图表 | 方法 | 引擎 | 实例 | 现状债 |
|---|---|---|---|---|
| 组合价值/盈亏走势 | `renderPortfolioChart()` `app.js:856` | Chart.js | `canvas.__chart` | 轴色硬编码深色（`868-869`）；无渐变填充；重建未 destroy |
| 租赁走势 | `renderTrackerChart()` `app.js:758` | ApexCharts | `this._trackerChart` | `theme` 写死 `'dark'`（`814`）；无渐变 |
| 价格走势 | `renderPriceChart()` `app.js:1599` | ApexCharts | `this._priceChart` | 已按 `isDark` 切色（`1607`，可参考）|

跨图表债：`toggleTheme()`（`app.js:1715`）切主题后**不重建图表**，需补重建钩子（§5）。

现有可复用资产（**勿重造**）：`fmtMoney`（`app.js:866`，含「万」紧凑）、`fmtPct`（`867`）、`fmtTip`（`772`）；调色板 emerald `#10b981` / blue `#3b82f6` / amber `#f59e0b` / red `#ef4444` / pink `#ec4899`；字体 `ui-monospace, monospace`。

---

## 2. 数据盘点 → 图表提案（先做这步，别直接动手画）

**先读懂数据**：扫 `app/`（路由/模型）与 `static/app.js`（前端已有的数据数组，如 `portfolioData`/`trackerData`/持仓列表/品类等），列出可用维度。CS2 饰品库存典型维度：单品（名称/品质 rarity/磨损 wear-float/类型 weapon-knife-glove/枪皮系列）、成本价、当前市价、盈亏额/率、买入时间、持有时长、租赁收益、平台价差等。

**再提案一套图表**（保留现有 3 个 + 新增若干）。下面是**候选清单（你按真实字段裁剪/增补，最终自行评判）**：

| 候选图 | 图型 / 引擎 | 分析价值 |
|---|---|---|
| 组合市值/盈亏走势 | 面积折线 / Chart.js（升级现有）| 资产时间趋势（hero 渐变填充）|
| 持仓构成（按类型/品质）| 环形 doughnut / Chart.js | 仓位结构一眼看清 |
| 持仓价值分布（按单品/品类）| **树状图 treemap / ApexCharts** | 集中度、哪些品类占大头 |
| 单品盈亏 Top 涨/跌 | 横向条形（双向）/ Chart.js | 谁在赚/亏，排序直观 |
| 盈亏率分布 | 直方图/柱 / Chart.js | 整体盈亏健康度 |
| 品质 × 磨损 热力 | **heatmap / ApexCharts** | 哪类组合更值钱/集中 |
| 租赁收益走势 | 面积折线 / Chart.js（升级现有）| 现金流趋势 |
| 顶部统计卡 | stat cards（§4.6）| 总市值/总盈亏/持仓数/今日变动 速览 |

**提案产出**：给用户一句话×每图（「画什么数据 + 为什么有用 + 用什么图型」），再开始建 demo。

---

## 3. 颜色与主题单一源（所有图共用）

```js
const _isDark   = () => !document.documentElement.classList.contains('light');
const _gridColor = () => _isDark() ? 'rgba(51,65,85,0.2)'  : 'rgba(186,214,235,0.3)';
const _tickColor = () => _isDark() ? '#64748b'             : '#475569';
const CHART_COLORS = { emerald:'#10b981', blue:'#3b82f6', amber:'#f59e0b', red:'#ef4444', pink:'#ec4899', purple:'#8b5cf6' };
const PALETTE = [CHART_COLORS.blue, CHART_COLORS.amber, CHART_COLORS.emerald, CHART_COLORS.purple, CHART_COLORS.red, CHART_COLORS.pink];
const CHART_FONT = 'ui-monospace, monospace';
const _alpha = (hex, a='14') => hex + a;   // hex + 两位 alpha
```

---

## 4. KOL 视觉工具箱（核心：让图表"好看"的技法）

> 这些是 KOL 图表精致感的来源。**深色基底不变**，但视觉处理照搬。每个 options 预设都是**工厂函数**（构建时调用、带 `()`），否则切主题后轴色烤死、暗→浅不可见。

### 4.1 共用预设（工厂函数）

```js
const _ttStyle = () => ({
  backgroundColor: _isDark() ? 'rgba(15,23,42,0.95)' : 'rgba(255,255,255,0.97)',
  titleColor: _isDark()?'#e2e8f0':'#0f172a', bodyColor:_isDark()?'#cbd5e1':'#334155',
  borderColor:_isDark()?'rgba(51,65,85,0.5)':'rgba(203,213,225,0.8)', borderWidth:1,
  padding:10, bodyFont:{ family:CHART_FONT, size:11 },
});
const _legend = (pos='top') => ({ position:pos, align:'start',
  labels:{ color:_tickColor(), font:{size:11,family:CHART_FONT}, usePointStyle:true, pointStyle:'rectRounded', boxWidth:8, padding:12 } });
const _axisX = () => ({ ticks:{ color:_tickColor(), font:{size:10,family:CHART_FONT}, maxRotation:0, autoSkip:true, maxTicksLimit:10 }, grid:{ color:_gridColor(), drawBorder:false } });
const _axisY = (extra={}) => ({ ticks:{ color:_tickColor(), font:{size:10,family:CHART_FONT}, ...extra }, grid:{ color:_gridColor(), drawBorder:false } });
const BASE = () => ({ responsive:true, maintainAspectRatio:false, resizeDelay:100, animation:false,
  interaction:{ mode:'index', intersect:false }, plugins:{ legend:_legend(), tooltip:_ttStyle() } });
```

### 4.2 折线渐变面积填充（最大观感差异）

```js
function _areaGradient(ctx, area, hex){
  const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, hex + '55');   // 贴线处较浓
  g.addColorStop(1, hex + '00');   // 向下淡出透明
  return g;
}
// 粗 + 平滑 + 渐变填充 + 白边点；多线叠加只给 hero 线 fill
function richLine(label, data, color, { axis='y', fill=false, dash=null, dense=false }={}){
  return { label, data, yAxisID:axis, borderColor:color,
    backgroundColor: fill ? (c)=>{const a=c.chart.chartArea; return a?_areaGradient(c.chart.ctx,a,color):null;} : 'transparent',
    fill, borderDash:dash||undefined, borderWidth:2.5, tension:0.4,
    pointRadius:dense?0:3, pointHoverRadius:dense?4:6,
    pointBackgroundColor:color, pointBorderColor:_isDark()?'#0f172a':'#fff', pointBorderWidth:2 };
}
```

### 4.3 圆角 + 渐变光泽柱

```js
function _barGradient(ctx, area, hex){
  const g = ctx.createLinearGradient(0, area.bottom, 0, area.top);
  g.addColorStop(0, hex+'40'); g.addColorStop(1, hex+'cc'); return g;   // 底淡顶浓 → 光泽
}
function richBars(label, data, color){
  return { label, data,
    backgroundColor:(c)=>{const a=c.chart.chartArea; return a?_barGradient(c.chart.ctx,a,color):color+'80';},
    borderColor:color, borderWidth:1.5, borderRadius:6, borderSkipped:false, maxBarThickness:30 };
}
// 分组柱：names.map((n,i)=> richBars(n, dataByName[n], PALETTE[i%PALETTE.length]))
```

### 4.4 横向排名条（Top N，如盈亏榜/品类市值）

```js
// options: indexAxis:'y'，X 轴金额、Y 轴标签；双向盈亏可按正负给 emerald/red
function rankBars(labels, values, {pos='#10b981', neg='#ef4444'}={}){
  return { labels, datasets:[{ data:values,
    backgroundColor:(c)=>{const a=c.chart.chartArea; if(!a)return pos; const v=c.raw; return _barGradient(c.chart.ctx,a, v>=0?pos:neg);},
    borderColor:(c)=> (c.raw>=0?pos:neg), borderWidth:1.5, borderRadius:5, borderSkipped:false }] };
}
// options:{ ...BASE(), indexAxis:'y', plugins:{legend:{display:false},tooltip:_ttStyle()},
//   scales:{ x:_axisY({callback:fmtMoney}), y:{ ticks:{color:_tickColor(),font:{size:10,family:CHART_FONT}}, grid:{display:false} } } }
```

### 4.5 环形 doughnut（构成/占比）

```js
new Chart(canvas, { type:'doughnut',
  data:{ labels, datasets:[{ data:counts, backgroundColor:labels.map((_,i)=>PALETTE[i%PALETTE.length]), borderWidth:0, hoverOffset:6 }] },
  options:{ responsive:true, maintainAspectRatio:false, cutout:'55%',
    plugins:{ legend:_legend('right'),
      tooltip:{ ..._ttStyle(), callbacks:{ label:ctx=>{const t=ctx.dataset.data.reduce((s,x)=>s+x,0)||1; return ctx.label+': '+ctx.parsed+' ('+Math.round(ctx.parsed/t*100)+'%)';} } } } } });
```

### 4.6 顶部统计卡（KOL 同款，深色版）

KOL 那种「¥48万 / 25年净利·19单」大字卡。Tailwind 深色实现：

```html
<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
  <div class="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 text-center">
    <div class="text-2xl font-extrabold tracking-tight text-emerald-400 font-mono">¥48万</div>
    <div class="mt-1 text-[11px] text-slate-400">总市值 · 持仓 132 件</div>
  </div>
  <!-- 总盈亏(正绿负红)、今日变动、持仓数… -->
</div>
```

### 4.7 树状图 / 热力图（用已加载的 ApexCharts）

Chart.js 不原生支持 treemap/heatmap，**用已加载的 ApexCharts**，主题用 `_isDark()` 切：

```js
// 持仓价值树状图：每块=一个单品/品类，面积∝市值
new ApexCharts(el, {
  chart:{ type:'treemap', height:320, fontFamily:CHART_FONT, background:'transparent', toolbar:{show:false} },
  theme:{ mode:_isDark()?'dark':'light' },
  series:[{ data: items.map(i=>({ x:i.name, y:i.market_value })) }],
  colors:[CHART_COLORS.blue, CHART_COLORS.emerald, CHART_COLORS.amber, CHART_COLORS.purple, CHART_COLORS.red],
  plotOptions:{ treemap:{ distributed:true, enableShades:true, shadeIntensity:0.4 } },
  tooltip:{ theme:_isDark()?'dark':'light', y:{ formatter:fmtMoney } },
  dataLabels:{ style:{ fontFamily:CHART_FONT, fontSize:'11px' } },
}).render();
// heatmap（品质×磨损）：series=[{name:品质, data:[{x:磨损档, y:数量/均值}]}]，type:'heatmap'
```

---

## 5. 工程层（生命周期 + 主题重建）

- **重建前 destroy**：Chart.js `canvas.__chart?.destroy()`；Apex `this._xxxChart?.destroy()`。
- **options 预设带 `()` 调用**（工厂函数，构建时取主题色）。
- **主题切换重建**：给 `toggleTheme()`（`app.js:1715`）末尾挂钩：

```js
toggleTheme(){
  this.theme = this.theme==='dark'?'light':'dark';
  localStorage.setItem('theme', this.theme);
  document.documentElement.classList.toggle('light', this.theme==='light');
  this.$nextTick(()=> this.rerenderActiveCharts());   // ★ 新增
},
rerenderActiveCharts(){
  // 按当前 tab/打开的视图重建所有图（Chart.js + Apex 都要）
}
```

---

## A. Demo B 专属：KOL 全套设计系统（液态玻璃 + 重做主题）

仅 **Demo B** 用。引入 KOL 设计 token 与玻璃卡片，用 `data-theme` 重做主题（替换 `.light`）。Demo A 跳过本节。

### A.1 设计 token（亮色优先 + 暗色 + 跟随系统）

```css
:root{
  --bg:#f2f2f5; --card:rgba(255,255,255,.65); --card-solid:#f8f8fa;
  --glass-border:rgba(0,0,0,.06);
  --glass-shadow:0 1px 8px rgba(0,0,0,.04); --glass-shadow-lg:0 6px 20px rgba(0,0,0,.08);
  --glass-inner:inset 1px 1px 1px 0 rgba(255,255,255,.4), inset -1px -1px 1px 0 rgba(255,255,255,.15);
  --blur:blur(12px) saturate(1.3);
  --primary:#3478F6; --pl:rgba(52,120,246,.05);
  --danger:#E5484D; --warn:#E5930E; --success:#30A46C; --info:#4BA0D0; --purple:#6E56CF;
  --text:#1c2024; --muted:#60646c; --muted2:#a0a4ab; --border:rgba(0,0,0,.07);
  --r:22px; --r-sm:14px; --r-pill:999px;
}
/* 暗色：把下面这组放进 :root[data-theme="dark"]{} 和
   @media(prefers-color-scheme:dark){ :root:not([data-theme]){} } 两处，内容相同： */
/*  --bg:#141416; --card:rgba(38,38,42,.6); --card-solid:#1e1e21;
    --glass-border:rgba(255,255,255,.08);
    --glass-shadow:0 1px 8px rgba(0,0,0,.15); --glass-shadow-lg:0 6px 20px rgba(0,0,0,.25);
    --glass-inner:inset 1px 1px 1px 0 rgba(255,255,255,.06), inset -1px -1px 1px 0 rgba(255,255,255,.02);
    --primary:#5B9BF7; --pl:rgba(91,155,247,.08);
    --danger:#E5484D; --warn:#E5930E; --success:#30A46C; --info:#5EB0E5; --purple:#9B8AFF;
    --text:#ececee; --muted:#8b8d94; --muted2:#4a4a50; --border:rgba(255,255,255,.07);          */
```

### A.2 玻璃卡片

```css
.glass{ background:var(--card); border-radius:var(--r); border:.5px solid var(--glass-border);
  box-shadow:var(--glass-shadow),var(--glass-inner); backdrop-filter:var(--blur); -webkit-backdrop-filter:var(--blur); }
.glass-solid{ background:var(--card-solid); border-radius:var(--r); border:.5px solid var(--glass-border);
  box-shadow:var(--glass-shadow),var(--glass-inner); }   /* 高频小卡片用实色，省 blur */
.stat-card{ padding:18px 12px; text-align:center; }
.stat-card .num{ font-size:28px; font-weight:800; letter-spacing:-.8px; }
.stat-card .lbl{ font-size:10.5px; color:var(--muted); margin-top:5px; }
```
> 与 Tailwind 共存：布局/间距仍可用 Tailwind 工具类，卡片表面与主题色走上面这些 CSS 变量（单一真源）。Demo B 的统计卡（§4.6）用 `.glass-solid .stat-card`，字色用 `--primary/--success` 等。

### A.3 三态主题（替换 .light hack）

```js
function applyTheme(t){ const r=document.documentElement;
  if(t==='dark') r.dataset.theme='dark'; else if(t==='light') r.dataset.theme='light'; else delete r.dataset.theme;
  t?localStorage.setItem('theme',t):localStorage.removeItem('theme');
  this.$nextTick ? this.$nextTick(()=>rerenderActiveCharts()) : rerenderActiveCharts();  // 切主题重建图表
}
function cycleTheme(){ const s=localStorage.getItem('theme'); applyTheme(!s?'light':s==='light'?'dark':null); } // 跟随系统→浅→深
applyTheme(localStorage.getItem('theme')||null);   // 默认跟随系统
```

### A.4 图表颜色改读 CSS 变量（Demo B）

Demo B 主题走 `data-theme`，把 §3 的判定改成读 CSS 变量，图表自动跟随亮/暗：

```js
const _isDark   = () => { const t=document.documentElement.getAttribute('data-theme'); return t==='dark' || (!t && matchMedia('(prefers-color-scheme:dark)').matches); };
const _gridColor = () => getComputedStyle(document.documentElement).getPropertyValue('--border').trim();
const _tickColor = () => getComputedStyle(document.documentElement).getPropertyValue('--muted').trim();
```
> 图表分类色仍用 §3 的 `PALETTE`（鲜明、亮暗都好看）；也可换 KOL 语义色 `--primary/--success/--warn`，自行取舍。

---

## 6. 执行步骤

1. **数据盘点 + 图表提案**（§2）→ 清单给用户/写进 demo 说明。**两个 demo 共用同一套图表提案与数据。**
2. 公共层：建 §3 颜色源 + §4 工具箱（richLine/_areaGradient/richBars/rankBars/doughnut/treemap…按提案取用）+ §5 工程层（destroy/工厂预设/重建钩子）。
3. 公共层：**升级现有 3 图**（portfolio→`richLine` 渐变填充 + destroy + 去硬编码；tracker/price 补渐变 + 主题感知）+ **新增提案图**（环形/树状/排名/热力/统计卡）。
4. **Demo A（深色精修）**：用 cs2 现有深色 slate 外壳 + 布局，套上 2/3 的图表。产出 `chart-lab-a.html`。
5. **Demo B（KOL 全套）**：引入 §A 设计系统（玻璃卡片 + `data-theme` 三态主题 + KOL 统计卡），§A.4 让图表读 CSS 变量，重排成 KOL 式卡片网格。产出 `chart-lab-b.html`。
6. 两个 demo 均调**现有后端真实数据**，给用户 **两个路径 + 截图**。确认后再合入主应用。

## 7. 验收清单

**两个 demo：**
- [ ] `chart-lab-a.html`（深色精修）+ `chart-lab-b.html`（KOL 全套重做）都产出，可并排对比
- [ ] 两者用**同一套图表提案 + 同一真实数据**，差异只在外壳（深色 slate vs KOL 液态玻璃）
- [ ] Demo B 已用 §A 的 `data-theme` 三态主题**替换 `.light` hack**，玻璃卡片 + KOL 统计卡到位；亮/浅/暗切换图表当场跟随变色

**分析深度：**
- [ ] 在保留现有图基础上，**新增了 ≥2 个有洞察力的图型**（如构成环形 / 价值树状 / 盈亏排名 / 分布），每个有明确分析价值
- [ ] 顶部统计卡速览关键指标（总市值/总盈亏/持仓数/今日变动等）

**视觉（KOL 标杆）：**
- [ ] hero 折线有**渐变面积填充** + 粗线 `2.5` + `tension:0.4`；稀疏图有白边点
- [ ] 柱图**圆角 6 + 渐变光泽**；环形 `cutout` + 无描边 + hover 偏移；树状/热力用 ApexCharts 且主题感知
- [ ] **After 明显比 Before 丰富**，和 KOL 截图放一起观感接近

**工程与边界：**
- [ ] 颜色/轴/tooltip 走 §3/§4.1 单一源；options 预设工厂函数带 `()`；切主题当场重建变色
- [ ] 重建前 destroy，无 canvas 复用报错；格式化用 `fmtMoney/fmtPct`
- [ ] demo 非破坏式，主应用未改；**未改动任何数据计算/接口逻辑**；新增图均为只读新视图
