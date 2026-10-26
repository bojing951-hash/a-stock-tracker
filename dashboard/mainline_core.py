#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主线识别算法 v3 — 容间断滑窗 + 三级分级
==========================================
替代旧的"刚性连续 TOP3"识别逻辑(annual_mainline_report.identify_mainlines /
switch_study_report.identify_mainline_periods)。

核心改动:
  1. 活跃池 = 周涨跌幅 TOP5 ∪ 成交额占比 TOP5(满足任一即"活跃")
  2. 容间断:允许中间断 1-2 周,只要滑窗内活跃率 ≥ 50%
  3. 三级分级:短期热点(2-3周) / 中期主线(4-8周) / 长期主线(8周+)

状态机参数(进入/持续/退出):
  - 进入:最近 4 周内 ≥ 3 周在活跃池
  - 持续:4 周滑窗内活跃周数 ≥ 2(50%)
  - 退出:连续 3 周不活跃,或滑窗活跃率跌破 50%

本模块同时兼容两种 weekly_df 契约:
  - annual 口径(calc_weekly_metrics):含"年"列,周标识为 (年,周) 二元组
  - switch 口径(calc_weekly_all):无"年"列,周标识为单一"周"int → 内部补哨兵年=0

返回的 mainline dict 同时携带两套下游兼容键名(annual 7 键 + switch 键 + 新字段),
使 annual / switch 两个报告文件的所有下游函数零改动即可使用。
"""

import numpy as np
import pandas as pd

# ── 状态机参数 ─────────────────────────────────────────
ENTER_WINDOW = 4      # 进入判定窗口(最近 N 周)
ENTER_THRESHOLD = 3   # 进入门槛:窗口内活跃周数 ≥ 此值
SUSTAIN_WINDOW = 4    # 持续判定滑窗
SUSTAIN_THRESHOLD = 2  # 持续门槛:滑窗内活跃周数 ≥ 此值(50%)
DEAD_STREAK = 3       # 连续不活跃周数达此值则退出


def _normalize_weekly_df(weekly_df):
    """统一周标识:返回 (df, sorted_weeks)。

    - 若无"年"列,补哨兵年=0(switch 口径,单年内周号唯一)。
    - sorted_weeks 为 (年, 周) 元组列表,按时间排序。
    """
    df = weekly_df.copy()
    if "年" not in df.columns:
        df["年"] = 0  # 哨兵年:switch 口径
    sorted_weeks = sorted(df[["年", "周"]].drop_duplicates().values.tolist())
    sorted_weeks = [tuple(w) for w in sorted_weeks]
    return df, sorted_weeks


def _compute_active_pool(df, sorted_weeks, pool_n=5,
                         min_ret=-1.0, bear_median=-2.0,
                         max_rank=20, amt_surge_pct=0.3):
    """每周活跃池 = 涨幅 TOP-N ∪ 成交额放量 TOP-N,带多重门槛 + 熊市周过滤。

    三重过滤(修复大市值行业靠天然高成交额混入):
      1. 单行业涨幅门槛:即使排名靠前,周跌幅超 min_ret(默认-1%)不算活跃。
      2. 成交额改为"放量幅度":成交额周环比增长率 TOP-N(默认需环比>+30%),
         而非绝对成交额排名。医药生物每周3000亿不变→环比0%→不进;通信500→800亿→+60%→进。
         (首周无上周数据,成交额条件作废,只看涨幅。)
      3. 双条件复核:无论走涨幅还是放量路径,该周涨幅全市场排名必须 ≤ max_rank(默认20,前2/3),
         排名21-31的一律不进活跃池。
      4. 熊市周过滤:若该周 TOP-N 中位数涨幅 < bear_median(默认-2%,普跌),整周作废。

    返回 (active_pool, bear_weeks):
      active_pool: {(年,周): set(行业名)}
      bear_weeks: set((年,周)) 熊市周集合
    """
    # 预算每个行业的成交额环比(按时间排序后 pct_change)
    df = df.copy()
    if "成交额占比" in df.columns or "周成交额" in df.columns:
        amt_col = "周成交额" if "周成交额" in df.columns else "成交额占比"
        df = df.sort_values(["行业", "年", "周"])
        df["_amt_prev"] = df.groupby("行业")[amt_col].shift(1)
        df["_amt_surge"] = np.where(
            df["_amt_prev"].fillna(0) > 0,
            df[amt_col] / df["_amt_prev"] - 1, np.nan)
        df["_rank"] = df.groupby(["年", "周"])["周涨跌幅"].rank(
            ascending=False, method="min").astype(int)

    active_pool = {}
    bear_weeks = set()
    for yw in sorted_weeks:
        y, w = yw
        sub = df[(df["年"] == y) & (df["周"] == w)]
        if sub.empty:
            active_pool[yw] = set()
            continue
        top_ret = sub.nlargest(pool_n, "周涨跌幅")
        # 熊市周:TOP-N 中位数 < bear_median → 整周作废
        if top_ret["周涨跌幅"].median() < bear_median:
            active_pool[yw] = set()
            bear_weeks.add(yw)
            continue
        # 路径A:涨幅 TOP-N + 涨幅门槛 + 排名复核
        cand_ret = top_ret[(top_ret["周涨跌幅"] > min_ret) &
                           (top_ret["_rank"] <= max_rank)]
        by_ret = set(cand_ret["行业"].tolist())
        # 路径B:成交额放量 TOP-N(环比>+amt_surge_pct)+ 涨幅门槛 + 排名复核
        by_amt = set()
        if "_amt_surge" in sub.columns:
            # 只在有上周数据的行业里选放量 TOP-N
            surged = sub[sub["_amt_surge"].notna()]
            if not surged.empty:
                top_surge = surged.nlargest(pool_n, "_amt_surge")
                cand_amt = top_surge[(top_surge["_amt_surge"] > amt_surge_pct) &
                                     (top_surge["周涨跌幅"] > min_ret) &
                                     (top_surge["_rank"] <= max_rank)]
                by_amt = set(cand_amt["行业"].tolist())
        active_pool[yw] = by_ret | by_amt
    return active_pool, bear_weeks


def _classify_level(span_weeks):
    """三级分级:基于总跨度周数(含间断)。"""
    if span_weeks >= 8:
        return "长期主线"
    elif span_weeks >= 4:
        return "中期主线"
    else:
        return "短期热点"


def _state_machine(df, sorted_weeks, active_pool, min_weeks=2):
    """容间断滑窗状态机。

    对每个行业独立扫描,产出 [(行业, 活跃周列表), ...]。
    活跃周列表 = 该段内(进入之后)所有进入活跃池的 (年,周) 元组,按时间顺序。

    关键:进入判定与段落累积分离。
      - `recent`: 记录最近 ENTER_WINDOW 周内该行业是否活跃(用于判定进入),独立于段落。
      - `active_weeks`: 仅在"已进入主线"后才累积,进入瞬间以进入窗口内的活跃周为起点。
    这样可避免"预热阶段的孤立活跃周被缝进正式主线",防止跨数十周的误缝合。
    """
    # (年,周) → 在 sorted_weeks 中的索引,用于算总跨度
    week_index = {yw: i for i, yw in enumerate(sorted_weeks)}

    # 行业状态
    # ind -> {entered, active_weeks, dead_streak, recent(int计数:最近ENTER_WINDOW周活跃数)}
    state = {}

    def _window_weeks(i, window):
        lo = max(0, i - window + 1)
        return sorted_weeks[lo:i + 1]

    finalized = []  # [(ind, active_weeks)]

    def _do_finalize(ind, st):
        if len(st["active_weeks"]) >= min_weeks:
            finalized.append((ind, list(st["active_weeks"])))

    def _reset(st):
        st.update({"entered": False, "active_weeks": [], "dead_streak": 0})

    for i, yw in enumerate(sorted_weeks):
        pool = active_pool.get(yw, set())

        # 本周活跃的行业,更新 recent 计数(滚动窗口)
        win_weeks = set(_window_weeks(i, ENTER_WINDOW))

        # 1) 处理本周活跃的行业
        for ind in pool:
            st = state.setdefault(ind, {"entered": False, "active_weeks": [],
                                        "dead_streak": 0})
            if st["entered"]:
                # 已进入:正常累积
                st["active_weeks"].append(yw)
                st["dead_streak"] = 0
            else:
                # 未进入:判定是否满足进入条件
                # 统计最近 ENTER_WINDOW 周内(含本周)该行业活跃数
                recent_count = 0
                for pw in _window_weeks(i, ENTER_WINDOW):
                    if ind in active_pool.get(pw, set()):
                        recent_count += 1
                if recent_count >= ENTER_THRESHOLD:
                    # 进入!以进入窗口内的活跃周为段落起点(不带预热历史)
                    enter_active = [pw for pw in _window_weeks(i, ENTER_WINDOW)
                                    if ind in active_pool.get(pw, set())]
                    st["entered"] = True
                    st["active_weeks"] = enter_active
                    st["dead_streak"] = 0

        # 2) 处理已进入但本周不活跃的行业
        for ind, st in state.items():
            if ind in pool:
                continue  # 本周活跃,已处理
            if not st["entered"]:
                continue  # 尚未进入主线,不累积、不结算
            st["dead_streak"] += 1
            # 退出条件 A:连续 DEAD_STREAK 周不活跃
            if st["dead_streak"] >= DEAD_STREAK:
                _do_finalize(ind, st)
                _reset(st)
                continue
            # 退出条件 B:滑窗活跃率跌破 50%
            win = set(_window_weeks(i, SUSTAIN_WINDOW))
            sustain_count = sum(1 for aw in st["active_weeks"] if aw in win)
            if sustain_count < SUSTAIN_THRESHOLD:
                _do_finalize(ind, st)
                _reset(st)

    # 3) 序列结束,收尾所有仍 entered 的
    for ind, st in state.items():
        if st["entered"]:
            _do_finalize(ind, st)

    return finalized


def _finalize_mainline(df, ind, active_weeks, sorted_weeks):
    """从活跃周列表构建完整 mainline dict(两套兼容键名 + 新字段)。

    返回 None 表示无效段(理论上不会,因为状态机已过滤 min_weeks)。
    """
    week_index = {yw: i for i, yw in enumerate(sorted_weeks)}
    active_weeks_sorted = sorted(active_weeks, key=lambda yw: week_index[yw])
    first_yw = active_weeks_sorted[0]
    last_yw = active_weeks_sorted[-1]

    # 总跨度周数(含中间间断):首末活跃周在 sorted_weeks 中的索引跨度
    span_weeks = week_index[last_yw] - week_index[first_yw] + 1
    active_count = len(active_weeks_sorted)
    active_rate = round(active_count / max(span_weeks, 1), 3)

    # 切出该行业在活跃周的行
    rows = df[(df["行业"] == ind) & (
        df.apply(lambda r: (int(r["年"]), int(r["周"])) in set(active_weeks_sorted), axis=1)
    )].copy()
    rows["__yw"] = list(zip(rows["年"].astype(int), rows["周"].astype(int)))
    rows = rows.sort_values("__yw")

    if rows.empty:
        return None

    # 涨跌幅/成交额/排名(仅按活跃周)
    pcts = rows["周涨跌幅"].tolist()
    amounts = rows["成交额占比"].tolist() if "成交额占比" in rows.columns else []
    cum = 1.0
    for p in pcts:
        cum *= (1 + p / 100)
    cum_return = round((cum - 1) * 100, 2)
    avg_amt = round(float(np.mean(amounts)), 2) if amounts else 0

    # 排名:若 weekly_df 已有"涨幅排名"列(switch 口径)直接用;否则现场算
    if "涨幅排名" in rows.columns:
        rank_seq = rows["涨幅排名"].astype(int).tolist()
    else:
        rank_seq = []
        for yw in active_weeks_sorted:
            y, w = yw
            wk = df[(df["年"] == y) & (df["周"] == w)].sort_values(
                "周涨跌幅", ascending=False)
            rk = wk.index.get_loc(rows[rows["__yw"] == yw].index[0]) + 1 if not rows[rows["__yw"] == yw].empty else 99
            rank_seq.append(int(rk))
    avg_rank = round(float(np.mean(rank_seq)), 1) if rank_seq else 0

    # 日期:首活跃周的"周开始" / 末活跃周的"周结束"
    first_row = rows.iloc[0]
    last_row = rows.iloc[-1]
    start_date = first_row["周开始"]
    end_date = last_row["周结束"]

    level = _classify_level(span_weeks)

    return {
        # ── 新算法核心字段 ──
        "行业": ind,
        "活跃周列表": active_weeks_sorted,       # list of (年,周)
        "活跃周数": active_count,
        "总跨度周数": span_weeks,
        "活跃率": active_rate,
        "级别": level,
        "排名序列": rank_seq,

        # ── annual 下游兼容(原 identify_mainlines 7 键) ──
        "开始日期": start_date,
        "结束日期": end_date,
        "持续周数": span_weeks,                  # 总跨度,与分级一致
        "累计涨幅": cum_return,
        "平均成交额占比": avg_amt,
        "周涨跌幅序列": pcts,

        # ── switch 下游兼容(原 identify_mainline_periods) ──
        "开始周": int(first_yw[1]),
        "结束周": int(last_yw[1]),
        "周列表": [int(yw[1]) for yw in active_weeks_sorted],  # 仅活跃周的"周"int
        "平均排名": avg_rank,
    }


def identify_mainlines_v3(weekly_df, top_n=3, min_weeks=2, pool_n=5):
    """容间断滑窗主线识别 v3 主入口。

    参数:
        weekly_df: 周度 DataFrame。需含列:
            行业, 周, 周涨跌幅, 成交额占比, 周开始, 周结束。
            可选: 年(annual 口径), 涨幅排名(switch 口径)。
        top_n: 旧签名兼容(未使用,活跃池深度由 pool_n 控制)。
        min_weeks: 最小活跃周数(默认 2)。
        pool_n: 活跃池深度(默认 5,TOP5)。

    返回 list[dict],每个 dict 同时携带 annual/switch 两套兼容键名 + 新字段。
    """
    if weekly_df is None or weekly_df.empty:
        return []
    df, sorted_weeks = _normalize_weekly_df(weekly_df)
    if not sorted_weeks:
        return []
    active_pool, bear_weeks = _compute_active_pool(df, sorted_weeks, pool_n=pool_n)
    raw = _state_machine(df, sorted_weeks, active_pool, min_weeks=min_weeks)
    mainlines = [_finalize_mainline(df, ind, aw, sorted_weeks)
                 for ind, aw in raw]
    mainlines = [m for m in mainlines if m is not None]

    # 注入熊市周(供逐周明细标灰)
    for m in mainlines:
        m["熊市周"] = [w for w in m.get("活跃周列表", []) if w in bear_weeks]

    # 改动三:累计涨幅门槛——亏钱的主线直接丢弃(任何级别都不算)
    dropped_neg = sum(1 for m in mainlines if m.get("累计涨幅", 0) < 0)
    mainlines = [m for m in mainlines if m.get("累计涨幅", 0) >= 0]

    # 统计输出
    levels = {"短期热点": 0, "中期主线": 0, "长期主线": 0}
    for m in mainlines:
        levels[m["级别"]] = levels.get(m["级别"], 0) + 1
    total = len(mainlines)
    print(f"  [主线识别 v3] 共识别 {total} 段: "
          f"短期热点 {levels['短期热点']}段 | "
          f"中期主线 {levels['中期主线']}段 | "
          f"长期主线 {levels['长期主线']}段")
    if dropped_neg:
        print(f"  [过滤] 丢弃 {dropped_neg} 段累计涨幅<0 的伪主线;熊市周 {len(bear_weeks)} 个")

    mainlines.sort(key=lambda x: x["开始日期"] if x["开始日期"] is not None
                   else pd.Timestamp.min)
    return mainlines
