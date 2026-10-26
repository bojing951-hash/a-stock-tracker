# 产能周期投资系统 v1.0

基于申万行业产能周期标注的 A 股行业择时系统：22 行业周期阶段判定 → 量化回测 → 实时指标预警 → 综合仪表盘，一站式日常使用工具。

核心假说：行业在「成长期/复苏期」超额收益为正，在「过剩期/出清期」为负。回测验证：成长期基准年化 +56.9%、过剩期 -12.5%（仅 4.3% 正收益），假说成立。

---

## 快速开始

```bash
# 依赖（akshare 已预装；其余为标准库）
pip install pandas numpy matplotlib

# 首次使用
python3 main.py status          # 查看数据状态
python3 main.py dashboard       # 终端仪表盘
python3 main.py dashboard --html  # 网页仪表盘（自动打开浏览器）
python3 main.py update          # 增量更新数据 + 预警检查
```

---

## 命令参考（main.py）

| 命令 | 说明 |
|---|---|
| `python3 main.py dashboard` | 终端 22 行业仪表盘（默认命令） |
| `python3 main.py dashboard --html` | 生成 HTML 仪表盘并打开浏览器 |
| `python3 main.py update` | 增量更新指数日线 + 6 类指标 + 自动预警 |
| `python3 main.py alert` | 运行预警检查（阶段转换 / 见底信号） |
| `python3 main.py backtest` | 重新运行全量回测（22 行业 × 3 模式，约 10 秒） |
| `python3 main.py report <行业>` | 生成单行业四维联动报告（调用 integrated_analyzer.py） |
| `python3 main.py status` | 简要状态：数据日期 + 预警计数 + CSV 记录数 |
| `python3 main.py help` | 显示帮助 |

---

## 目录结构

```
a_stock_tracker/
├── main.py                          统一命令行入口
├── run_daily.sh / run_weekly.sh     定时任务脚本
├── README.md
│
├── data_feeds/                      数据接入层（阶段1）
│   ├── fetch_sw_index.py            申万行业指数日线拉取
│   ├── fetch_indicators.py          6 类核心指标拉取
│   ├── incremental_update.py        增量更新
│   └── scheduler.py                 调度说明（crontab/launchd 模板）
│
├── backtest/                        量化回测（阶段2）
│   ├── cycle_timing_strategy.py     策略类 CycleTimingBacktest
│   ├── backtest_engine.py           批量引擎 + 阶段/deviation 分析
│   ├── make_charts.py               可视化生成
│   └── backtest_results/
│       ├── cycle_timing_summary.csv   22 行业三模式汇总
│       ├── phase_effectiveness.csv    6 阶段效果验证
│       ├── deviation_analysis.csv     4 类偏离影响
│       ├── chart_1~6_*.png            6 张图表
│       └── backtest_charts.html       回测图表汇总
│
├── dashboard/                       仪表盘与预警（阶段3/4）
│   ├── indicator_registry.py        22 行业指标注册表（配置中心）
│   ├── alert_engine.py              预警引擎
│   ├── cycle_dashboard.py           综合仪表盘
│   └── cycle_dashboard.html         网页仪表盘
│
└── raw_data/                        原始数据
    ├── industry_cycle.csv           107 条周期标注（15 列）
    ├── sw_index_mapping.json        22 行业→申万指数映射
    ├── sw_industry_daily.csv        申万行业日线全集（184,902 行）
    ├── index_daily/{行业}.csv        22 行业标准日线（date,open,close,high,low,volume,amount）
    ├── indicators/                  6 类核心指标 CSV
    └── alerts/alerts_log.csv        预警日志
```

---

## 数据说明

### industry_cycle.csv（周期标注，107 行 × 15 列）

| 字段 | 含义 |
|---|---|
| 行业名称 | 22 行业之一 |
| 起始日期 / 结束日期 | 周期段起止（含"至今"、"2022-11"年月格式） |
| 周期阶段 / 周期阶段_标准化 | 原始标注 / 清洗后（**策略用标准化列**） |
| deviation_type | 偏离类型：时滞偏离 / 逻辑切换 / 系统性掩盖 / 结构性对冲（29 条非空） |
| 判定依据 / 核心产品价格 / 龙头capex方向 / 产能利用率 / 产能状态 / 价格趋势 / 需求状态 | 周期判定证据链 |

**6 个标准化周期阶段**：成长期(28) / 过剩期(25) / 景气顶部(17) / 复苏期(16) / 成熟稳定期(13) / 出清期(8)

### 6 类核心指标（raw_data/indicators/）

| 指标 | 文件 | 用途 | 最新值 |
|---|---|---|---|
| 碳酸锂期货 LC0 | lithium_carbonate_futures.csv | 能源金属/电池 | 16.05 万元/吨 |
| 上海金基准价 | gold_price_sge.csv | 贵金属 | 940.33 元/克 |
| 两融余额（上交所） | margin_balance.csv | 非银金融 | 15,093 亿元 |
| 螺纹钢现货 | rebar_spot.csv | 钢铁/化工 | 3,169 元/吨 |
| 生猪价格 | hog_price.csv | 养殖业 | 9.40 元/公斤 |
| 申万一级估值 | sw_valuation.csv | 全行业 | 31 行业 PE/PB/股息率 |

---

## 预警规则说明

### 阶段转换触发（dashboard/indicator_registry.py，47 条规则）

每个行业定义从当前阶段出发的转换条件，规则由 `alert_engine.py` 自动解析：

```
数值条件：碳酸锂期货价 > 100000
区间+持续：上海金基准价 在 800-950 持续60日   (时序指标验持续性；PE快照→人工确认)
技术条件：指数突破60日均线 / 指数60日涨幅 > 40% / RSI_14 > 80
持续条件：碳酸锂期货价 > 100000 持续20日
回落条件：碳酸锂期货价 从峰值回落 > 30%
人工确认：含"企稳/转正/同比"等定性词 → 标记 pending_manual
```

### 领先信号（解决"出清期踏空"）

当前处于「出清期/过剩期」的行业，额外检测 3 个见底信号（≥2 个触发预警）：
1. 指数站上 60 日均线
2. 近 20 日涨幅 > 15%（V 型反转）
3. 放量（20 日均量 > 60 日均量 × 1.3）

### 三类预警级别

- 🔴 **转换触发**：满足阶段转换全部条件 → 需更新 industry_cycle.csv
- 🟡 **见底候选**：出清/过剩期出现见底信号 → 准备转入复苏期，避免踏空
- 🟢 **正常**：维持当前判断

---

## 回测结果摘要

**策略**（binary 模式）：成长/复苏满仓、过剩/出清空仓、景气顶部半仓、成熟稳定 75%。

| 指标 | 结果 |
|---|---|
| 全行业平均超额（binary） | **+2.56%** |
| 正超额行业 | 16/22（73%） |
| A 组（2015 起）平均超额 | +1.4% |
| B 组（2021 起）平均超额 | +5.0% |

**周期阶段效果验证**（基准满仓年化）：
- 成长期 **+56.9%**（100% 正）✅ | 复苏期 +23.6%（87% 正）✅
- 过剩期 **-12.5%**（仅 4.3% 正）✅ | 出清期 +15.9%（见底反弹，⚠️ 踏空风险）

**deviation_type 影响**：
- 时滞偏离：误判率 40%，超额损失 +12.8%（**策略最大敌人**）
- 逻辑切换：误判率 22%，超额损失 +3.8%
- 系统性掩盖 / 结构性对冲：策略反而跑赢基准

**4 个 CONSERVATIVE_ONLY 行业**（binary 失效，改保守模式）：基础化工、煤炭、有色金属、消费电子

---

## 定时任务配置

**crontab**（交易日 17:00 收盘后）：
```bash
crontab -e
0 17 * * 1-5 /path/to/a-stock-tracker/run_daily.sh  >> .../daily.log 2>&1
30 17 * * 5 /path/to/a-stock-tracker/run_weekly.sh >> .../weekly.log 2>&1
```

**launchd**（推荐，支持睡眠唤醒补跑）：运行 `python3 data_feeds/scheduler.py` 获取 plist 模板，放入 `~/Library/LaunchAgents/` 后 `launchctl load`。

---

## 已知限制

1. **10 个 B 组行业 2021 年前无日线数据**（光伏/半导体/电池/能源金属/风电/消费电子/医疗器械/贵金属/计算机设备/软件开发）——申万 2021 改版后新增的二级板块，2015-2020 周期段无价格数据，回测自动跳过。
2. **行业口径差异**：周期标注用 22 行业（含"有色金属/通信设备"），与映射 JSON（含"钢铁/养殖业"）有 4 个不同；回测以周期 CSV 口径为准。
3. **manual 指标需人工录入**：版号发放数、票房、AI 服务器预期、装机量、招标量等无法自动采集，预警引擎标记为 pending_manual。
4. **网络环境**：本机代理 7890 返回 502 不可用，所有脚本启动即清代理强制直连；eastmoney 实时行情接口间歇性被重置，故指数以本地 `sw_industry_daily.csv` 为主源，akshare 仅作增量补充（失败降级，不中断）。
5. **两融余额为上交所口径**（akshare 稳定接口），趋势可用；沪深合并口径需另接东方财富页面。
6. **回测不含交易成本/滑点**，position 调整为瞬时；后续可加 cost 参数。
7. **申万估值是日度快照**（单值），无法验证"PE 在区间持续 N 日"，此类规则降级为人工确认。
8. **deviation_type 为事后标注**，预警引擎无法实时识别；领先信号（见底候选）是补偿机制，非完全替代。
9. **`report` 命令**调用父目录的 `integrated_analyzer.py`（项目原始位置），其数据口径为父目录版本。
10. **预警日志累积**：每次运行追加，不做去重；如需清理可删除 `raw_data/alerts/alerts_log.csv` 重新生成。

---

## 阶段构建记录

- **阶段1**：数据接入层（22 行业映射 + 日线拉取 + 6 类指标）
- **阶段2**：量化回测（产能周期择时策略，22 行业 × 3 模式）
- **阶段3**：自动化追踪（指标注册表 + 预警引擎 + 增量更新 + 定时调度）
- **阶段4**：仪表盘整合（cycle_dashboard + main.py 统一入口）
