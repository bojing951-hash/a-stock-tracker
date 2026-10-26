#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2025 全年主线演变报告生成器
基于 31 个申万一级行业日线数据，生成：
1. 主线时间轴（按实际切换节点分段，非固定季度）
2. 每个切换点的 31 行业横截面快照
3. 每条主线的完整生命周期（发酵→加速→顶峰→衰退→替换）
4. 产能周期标签叠加
5. 输出交互式 HTML 报告 + 结构化 CSV
"""

import os
import sys
import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── 路径 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_data"
SW31_DIR = RAW_DIR / "sw31_daily"
REPORT_DIR = BASE_DIR / "dashboard" / "replay_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── 31 行业代码 ──────────────────────────────────────
SW31_INDUSTRIES = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁",
    "801050": "有色金属", "801080": "电子",     "801110": "家用电器",
    "801120": "食品饮料", "801130": "纺织服饰", "801140": "轻工制造",
    "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产",   "801200": "商贸零售", "801210": "社会服务",
    "801230": "综合",     "801710": "建筑材料", "801720": "建筑装饰",
    "801730": "电力设备", "801740": "国防军工", "801750": "计算机",
    "801760": "传媒",     "801770": "通信",     "801780": "银行",
    "801790": "非银金融", "801880": "汽车",     "801890": "机械设备",
    "801950": "煤炭",     "801960": "石油石化", "801970": "环保",
    "801980": "美容护理",
}

SECTOR_TO_SW1 = {
    "光伏设备": "电力设备", "锂电池": "电力设备", "风电设备": "电力设备",
    "半导体": "电子", "消费电子": "电子", "LED": "电子",
    "汽车零部件": "汽车", "新能源汽车": "汽车",
    "白酒": "食品饮料", "乳品": "食品饮料",
    "化学制药": "医药生物", "医疗器械": "医药生物", "中药": "医药生物",
    "房地产开发": "房地产",
    "煤炭开采": "煤炭",
    "能源金属": "有色金属", "工业金属": "有色金属", "贵金属": "有色金属",
    "通信设备": "通信",
    "计算机设备": "计算机", "软件开发": "计算机",
    "传媒": "传媒",
}

# ── 产能周期颜色 & 样式映射 ──────────────────────────
CYCLE_COLORS = {
    "成长期":     {"bg": "#064e3b", "text": "#34d399", "border": "#059669"},
    "景气顶部":   {"bg": "#78350f", "text": "#fbbf24", "border": "#d97706"},
    "过剩期":     {"bg": "#4c1d1d", "text": "#f87171", "border": "#dc2626"},
    "出清期":     {"bg": "#312e81", "text": "#a78bfa", "border": "#7c3aed"},
    "复苏期":     {"bg": "#1e3a5f", "text": "#60a5fa", "border": "#3b82f6"},
    "成熟稳定期": {"bg": "#1f2937", "text": "#9ca3af", "border": "#4b5563"},
    "未标注":     {"bg": "#111827", "text": "#6b7280", "border": "#374151"},
}


def _get_cycle_class(cyc):
    """根据周期阶段名返回 CYCLE_COLORS 的 key（支持'高位盘整期'等非标准名归入）"""
    cyc = str(cyc)
    for key in ["成长期", "景气顶部", "过剩期", "出清期", "复苏期", "成熟稳定期"]:
        if key in cyc:
            return key
    return "未标注"


def load_catalysts(year=2025):
    path = RAW_DIR / "catalyst_events_full.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["日期"])
    df = df[df["日期"].dt.year == year].copy()
    return df


def load_cycle_phases():
    """
    加载产能周期标签，返回 dict: {一级行业名: 最新阶段}
    优先级: sw31_cycle_phases.csv(31行业完整标注) >
            quarterly_with_cycle_phase.csv > industry_cycle.csv
    """
    phases = {}

    # 方法0(最优): sw31_cycle_phases.csv — 31 行业完整标注
    sw31_path = RAW_DIR / "sw31_cycle_phases.csv"
    if sw31_path.exists():
        df = pd.read_csv(sw31_path)
        name_col = next((c for c in df.columns if "行业" in c and "代码" not in c), None)
        phase_col = next((c for c in df.columns if "周期" in c or "阶段" in c), None)
        if name_col and phase_col:
            for _, row in df.iterrows():
                name = str(row[name_col])
                phase = row.get(phase_col, "")
                if name and pd.notna(phase) and str(phase).strip():
                    phases[name] = str(phase)
        if len(phases) >= 25:
            return phases

    # 二级/细分行业 → 申万一级 的映射(周期CSV口径含22个细分行业)
    sector_to_sw1_ext = dict(SECTOR_TO_SW1)
    sector_to_sw1_ext.update({
        "计算机设备": "计算机", "软件开发": "计算机",
        "通信设备": "通信",
        "汽车零部件": "汽车",
        "医疗器械": "医药生物",
        "半导体": "电子", "消费电子": "电子",
        "光伏设备": "电力设备", "电池": "电力设备", "风电设备": "电力设备",
        "能源金属": "有色金属", "贵金属": "有色金属",
        "养殖业": "农林牧渔",
    })

    qcp = RAW_DIR / "quarterly_with_cycle_phase.csv"
    if qcp.exists():
        df = pd.read_csv(qcp)
        name_col = next((c for c in df.columns if "行业" in c), None)
        phase_col = next((c for c in df.columns if "周期" in c or "阶段" in c or "cycle" in c.lower()), None)
        if name_col and phase_col and "季度" in df.columns:
            latest_q = df["季度"].max()
            sub = df[df["季度"] == latest_q]
            for _, row in sub.iterrows():
                name = str(row[name_col])
                phase = row.get(phase_col, "")
                if pd.notna(phase) and str(phase).strip():
                    # 映射到一级(若本身不是一级)
                    sw1 = sector_to_sw1_ext.get(name, name)
                    if sw1 in SW31_INDUSTRIES.values():
                        phases[sw1] = str(phase)

    ic = RAW_DIR / "industry_cycle.csv"
    if ic.exists():
        df = pd.read_csv(ic, encoding="utf-8-sig")
        name_col = next((c for c in df.columns if "行业" in c), None)
        phase_col = next((c for c in df.columns if "阶段" in c), None)
        if name_col and phase_col:
            for sector, g in df.groupby(df[name_col].astype(str)):
                latest = g.iloc[-1]
                phase = str(latest[phase_col])
                sw1 = sector_to_sw1_ext.get(sector, sector)
                if sw1 in SW31_INDUSTRIES.values():
                    phases[sw1] = phase
    return phases


def load_sw31_data(year=2025):
    all_path = SW31_DIR / "sw31_daily_all.csv"
    if not all_path.exists():
        print(f"[ERROR] 未找到 {all_path}")
        sys.exit(1)

    df = pd.read_csv(all_path)
    date_col = [c for c in df.columns if "日期" in c or "date" in c.lower()]
    if date_col:
        df.rename(columns={date_col[0]: "日期"}, inplace=True)
    df["日期"] = pd.to_datetime(df["日期"])
    # 优先匹配"行业名称"，避免误取"行业代码"
    name_col = next((c for c in df.columns if c.strip() == "行业名称"),
                    next((c for c in df.columns if "名称" in c), None))
    if name_col is None:
        name_col = next((c for c in df.columns if "行业" in c and "代码" not in c), None)
    if name_col:
        df.rename(columns={name_col: "行业"}, inplace=True)
    close_col = [c for c in df.columns if "收盘" in c]
    if close_col:
        df.rename(columns={close_col[0]: "收盘"}, inplace=True)
    amount_col = [c for c in df.columns if "成交额" in c]
    if amount_col:
        df.rename(columns={amount_col[0]: "成交额"}, inplace=True)

    start = pd.Timestamp(f"{year}-01-01") - timedelta(days=30)
    end = pd.Timestamp(f"{year}-12-31") + timedelta(days=30)
    df = df[(df["日期"] >= start) & (df["日期"] <= end)].copy()

    industry_data = {}
    for name, grp in df.groupby("行业"):
        grp = grp.sort_values("日期").reset_index(drop=True)
        industry_data[name] = grp
    return industry_data, df


def calc_weekly_metrics(industry_data, year=2025):
    records = []
    for name, df in industry_data.items():
        df = df[df["日期"].dt.year == year].copy()
        if df.empty:
            continue
        df["周"] = df["日期"].dt.isocalendar().week.astype(int)
        df["年"] = df["日期"].dt.year
        for (y, w), grp in df.groupby(["年", "周"]):
            grp = grp.sort_values("日期")
            if len(grp) < 1:
                continue
            week_start = grp["日期"].iloc[0]
            week_end = grp["日期"].iloc[-1]
            open_price = grp["收盘"].iloc[0]
            close_price = grp["收盘"].iloc[-1]
            pct = (close_price / open_price - 1) * 100 if open_price > 0 else 0
            amount = grp["成交额"].sum() if "成交额" in grp.columns else 0
            records.append({"周开始": week_start, "周结束": week_end, "年": y,
                            "周": w, "行业": name, "周涨跌幅": round(pct, 2),
                            "周成交额": amount})
    wdf = pd.DataFrame(records)
    if not wdf.empty and "周成交额" in wdf.columns:
        week_total = wdf.groupby(["年", "周"])["周成交额"].transform("sum")
        wdf["成交额占比"] = np.where(week_total > 0,
                                     (wdf["周成交额"] / week_total * 100).round(2), 0)
    return wdf


def identify_mainlines(weekly_df, top_n=3, min_weeks=2):
    """容间断滑窗主线识别 v3(薄包装,调用 mainline_core)。

    核心改动 vs 旧版"刚性连续 TOP3":
      - 活跃池 = 周涨跌幅 TOP5 ∪ 成交额占比 TOP5(满足任一即活跃)
      - 容间断:允许中间断 1-2 周,滑窗活跃率 ≥ 50% 即延续
      - 三级分级:短期热点 / 中期主线 / 长期主线(详见 mainline_core)
    返回 dict 兼容旧键名(行业/开始日期/结束日期/持续周数/累计涨幅/平均成交额占比/周涨跌幅序列)
    外加新字段(级别/总跨度周数/活跃周数/活跃率/排名序列 等)。
    """
    from dashboard.mainline_core import identify_mainlines_v3
    return identify_mainlines_v3(weekly_df, top_n=top_n, min_weeks=min_weeks, pool_n=5)


def analyze_lifecycle(mainline, industry_data, year=2025):
    ind_name = mainline["行业"]
    start = mainline["开始日期"]
    end = mainline["结束日期"]
    if ind_name not in industry_data or start is None or end is None:
        return mainline
    df = industry_data[ind_name].copy().sort_values("日期")
    pre_start = start - timedelta(days=21)
    pre_df = df[(df["日期"] >= pre_start) & (df["日期"] < start)]
    if not pre_df.empty and "成交额" in pre_df.columns:
        pre_amounts = pre_df["成交额"].values
        if len(pre_amounts) >= 4:
            first_half = pre_amounts[:len(pre_amounts)//2].mean()
            second_half = pre_amounts[len(pre_amounts)//2:].mean()
            ferment_signal = (second_half / first_half - 1) * 100 if first_half > 0 else 0
        else:
            ferment_signal = 0
        ferment_return = (pre_df["收盘"].iloc[-1] / pre_df["收盘"].iloc[0] - 1) * 100 if len(pre_df) >= 2 else 0
    else:
        ferment_signal = 0
        ferment_return = 0
    main_df = df[(df["日期"] >= start) & (df["日期"] <= end)]
    peak_date, to_peak_return, from_peak_return = None, 0, 0
    if not main_df.empty:
        peak_idx = main_df["收盘"].idxmax()
        peak_date = main_df.loc[peak_idx, "日期"]
        peak_price = main_df.loc[peak_idx, "收盘"]
        start_price = main_df["收盘"].iloc[0]
        end_price = main_df["收盘"].iloc[-1]
        to_peak_return = (peak_price / start_price - 1) * 100 if start_price > 0 else 0
        from_peak_return = (end_price / peak_price - 1) * 100 if peak_price > 0 else 0
    post_end = end + timedelta(days=21)
    post_df = df[(df["日期"] > end) & (df["日期"] <= post_end)]
    post_return = (post_df["收盘"].iloc[-1] / post_df["收盘"].iloc[0] - 1) * 100 if not post_df.empty and len(post_df) >= 2 else 0
    mainline["发酵期成交额变化"] = round(ferment_signal, 1)
    mainline["发酵期涨幅"] = round(ferment_return, 2)
    mainline["顶峰日期"] = peak_date
    mainline["起点到顶峰涨幅"] = round(to_peak_return, 2)
    mainline["顶峰到结束跌幅"] = round(from_peak_return, 2)
    mainline["退出后2周涨幅"] = round(post_return, 2)
    return mainline


def detect_switch_points(mainlines):
    if len(mainlines) < 2:
        return []
    switches = []
    sorted_ml = sorted(mainlines, key=lambda x: x["结束日期"] if x["结束日期"] is not None else pd.Timestamp.max)
    for ml in sorted_ml:
        end_date = ml["结束日期"]
        if end_date is None:
            continue
        successors = []
        for ml2 in mainlines:
            if ml2["行业"] == ml["行业"]:
                continue
            s2 = ml2["开始日期"]
            if s2 is not None:
                delta = (s2 - end_date).days
                if -7 <= delta <= 14:
                    successors.append(ml2)
        if successors:
            successors.sort(key=lambda x: abs((x["开始日期"] - end_date).days))
            for succ in successors[:3]:
                switches.append({"切换日期": end_date, "退出主线": ml["行业"],
                                 "退出主线累计涨幅": ml["累计涨幅"], "退出主线持续周数": ml["持续周数"],
                                 "新主线": succ["行业"], "新主线累计涨幅": succ["累计涨幅"],
                                 "新主线持续周数": succ["持续周数"],
                                 "间隔天数": (succ["开始日期"] - end_date).days})
    seen = set()
    unique = []
    for s in switches:
        key = (str(s["切换日期"])[:10], s["退出主线"], s["新主线"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    unique.sort(key=lambda x: x["切换日期"])
    return unique


def generate_cross_section(switch_date, weekly_df, industry_data, window_days=7):
    snapshot = []
    for name, df in industry_data.items():
        df = df.sort_values("日期")
        pre_start = switch_date - timedelta(days=window_days + 5)
        pre = df[(df["日期"] >= pre_start) & (df["日期"] <= switch_date)]
        post_end = switch_date + timedelta(days=window_days + 5)
        post = df[(df["日期"] > switch_date) & (df["日期"] <= post_end)]
        pre_return = (pre["收盘"].iloc[-1] / pre["收盘"].iloc[0] - 1) * 100 if not pre.empty and len(pre) >= 2 else 0
        post_return = (post["收盘"].iloc[-1] / post["收盘"].iloc[0] - 1) * 100 if not post.empty and len(post) >= 2 else 0
        pre_amount = pre["成交额"].mean() if not pre.empty and "成交额" in pre.columns else 0
        post_amount = post["成交额"].mean() if not post.empty and "成交额" in post.columns else 0
        amount_change = (post_amount / pre_amount - 1) * 100 if pre_amount > 0 else 0
        snapshot.append({"行业": name, "切换前涨跌幅": round(pre_return, 2),
                         "切换后涨跌幅": round(post_return, 2),
                         "成交额变化": round(amount_change, 1),
                         "动向": "↑加速" if post_return > pre_return + 2 else ("↓减速" if post_return < pre_return - 2 else "→持平")})
    return sorted(snapshot, key=lambda x: x["切换后涨跌幅"], reverse=True)


def judge_market_regime(date, industry_data):
    all_returns = []
    for name, df in industry_data.items():
        df = df.sort_values("日期")
        recent = df[df["日期"] <= date].tail(20)
        if len(recent) >= 2:
            all_returns.append((recent["收盘"].iloc[-1] / recent["收盘"].iloc[0] - 1) * 100)
    if not all_returns:
        return "未知", 0
    avg_return = np.mean(all_returns)
    up_ratio = sum(1 for r in all_returns if r > 0) / len(all_returns)
    if avg_return > 5 and up_ratio > 0.7:
        regime = "牛市加速"
    elif avg_return > 2 and up_ratio > 0.6:
        regime = "牛市中段"
    elif avg_return > 0 and up_ratio > 0.5:
        regime = "震荡偏多"
    elif avg_return > -2:
        regime = "震荡市"
    elif avg_return > -5:
        regime = "震荡偏空"
    else:
        regime = "熊市下行" if up_ratio < 0.3 else "熊市反弹"
    return regime, round(avg_return, 2)


def segment_phases(mainlines, switches, industry_data, catalysts, cycle_phases, year=2025):
    if not mainlines:
        return []
    key_dates = set()
    for ml in mainlines:
        if ml["开始日期"] is not None:
            key_dates.add(ml["开始日期"])
        if ml["结束日期"] is not None:
            key_dates.add(ml["结束日期"])
    key_dates = sorted(key_dates)
    if not key_dates:
        return []
    merged_dates = [key_dates[0]]
    for d in key_dates[1:]:
        if (d - merged_dates[-1]).days > 7:
            merged_dates.append(d)
    year_start = pd.Timestamp(f"{year}-01-01")
    year_end = pd.Timestamp(f"{year}-12-31")
    boundaries = sorted(set([year_start] + merged_dates + [year_end]))
    clean_boundaries = [boundaries[0]]
    for b in boundaries[1:]:
        if (b - clean_boundaries[-1]).days > 5:
            clean_boundaries.append(b)
    phases = []
    for i in range(len(clean_boundaries) - 1):
        phase_start = clean_boundaries[i]
        phase_end = clean_boundaries[i + 1]
        active_mainlines = [ml for ml in mainlines if ml["开始日期"] is not None and ml["结束日期"] is not None
                            and ml["开始日期"] <= phase_end and ml["结束日期"] >= phase_start]
        mid_date = phase_start + (phase_end - phase_start) / 2
        regime, avg_ret = judge_market_regime(mid_date, industry_data)
        matched_catalysts = []
        if not catalysts.empty:
            mask = (catalysts["日期"] >= phase_start) & (catalysts["日期"] <= phase_end)
            for _, row in catalysts[mask].iterrows():
                matched_catalysts.append({"日期": row["日期"].strftime("%m-%d"),
                                          "事件": row.get("事件名称", ""),
                                          "类型": row.get("事件类型", ""),
                                          "关联行业": row.get("关联行业", "")})
        phase_cycles = {ml["行业"]: cycle_phases.get(ml["行业"], "未标注") for ml in active_mainlines}
        phases.append({"阶段序号": i + 1, "开始日期": phase_start, "结束日期": phase_end,
                       "持续天数": (phase_end - phase_start).days, "大盘状态": regime,
                       "大盘均涨幅": avg_ret, "活跃主线": active_mainlines,
                       "催化剂": matched_catalysts, "产能周期": phase_cycles})
    phases = [p for p in phases if p["持续天数"] >= 3]
    for i, p in enumerate(phases):
        p["阶段序号"] = i + 1
    return phases


def merge_phases(phases, max_days=60):
    """
    智能合并相邻阶段:
    1. 主线重叠率>=50% 或 大盘状态相同 → 合并
    2. 合并后不超过 max_days 天
    3. 当前阶段有重大催化剂(催化剂列表非空) → 不合并(保留独立)
    """
    if len(phases) <= 1:
        return phases
    merged = [phases[0].copy()]
    for i in range(1, len(phases)):
        prev = merged[-1]
        curr = phases[i]
        combined_days = (curr["结束日期"] - prev["开始日期"]).days
        can_merge = combined_days <= max_days
        prev_inds = set(ml["行业"] for ml in prev["活跃主线"])
        curr_inds = set(ml["行业"] for ml in curr["活跃主线"])
        if prev_inds and curr_inds:
            overlap_ratio = len(prev_inds & curr_inds) / max(len(prev_inds), len(curr_inds))
        elif not prev_inds and not curr_inds:
            overlap_ratio = 1.0
        else:
            overlap_ratio = 0.0
        same_regime = prev["大盘状态"] == curr["大盘状态"]
        has_major_catalyst = len(curr["催化剂"]) > 0
        if can_merge and not has_major_catalyst and (overlap_ratio >= 0.5 or same_regime):
            merged[-1]["结束日期"] = curr["结束日期"]
            merged[-1]["持续天数"] = (merged[-1]["结束日期"] - merged[-1]["开始日期"]).days
            existing = {ml["行业"] for ml in merged[-1]["活跃主线"]}
            for ml in curr["活跃主线"]:
                if ml["行业"] not in existing:
                    merged[-1]["活跃主线"].append(ml)
                    existing.add(ml["行业"])
            merged[-1]["催化剂"].extend(curr["催化剂"])
            merged[-1]["产能周期"].update(curr["产能周期"])
            if curr["持续天数"] > prev["持续天数"]:
                merged[-1]["大盘状态"] = curr["大盘状态"]
                merged[-1]["大盘均涨幅"] = curr["大盘均涨幅"]
        else:
            merged.append(curr.copy())
    for i, p in enumerate(merged):
        p["阶段序号"] = i + 1
    return merged


def generate_mini_bar_chart_html(phase, industry_data, cycle_phases):
    """单个阶段 31 行业涨跌幅迷你条形图(含周期标签+主线标记+TOP/BOT)"""
    start = phase["开始日期"]
    end = phase["结束日期"]
    records = []
    for name, df in industry_data.items():
        df = df.sort_values("日期")
        sub = df[(df["日期"] >= start) & (df["日期"] <= end)]
        ret = (sub["收盘"].iloc[-1] / sub["收盘"].iloc[0] - 1) * 100 if len(sub) >= 2 else 0
        records.append({"行业": name, "涨跌幅": round(ret, 2),
                        "周期": cycle_phases.get(name, "未标注")})
    records.sort(key=lambda x: x["涨跌幅"], reverse=True)
    if not records:
        return ""
    max_abs = max(abs(r["涨跌幅"]) for r in records) or 1
    active_names = set(ml["行业"] for ml in phase["活跃主线"])
    bars_html = ""
    n = len(records)
    for i, r in enumerate(records):
        pct = r["涨跌幅"]
        bar_width = min(abs(pct) / max_abs * 100, 100)
        if pct > 0:
            color = "#ef4444" if pct > 5 else ("#f87171" if pct > 2 else "#fca5a5")
            bar_style = f"width:{bar_width:.1f}%;background:{color};margin-left:50%;"
        elif pct < 0:
            color = "#22c55e" if pct < -5 else ("#4ade80" if pct < -2 else "#86efac")
            bar_style = f"width:{bar_width:.1f}%;background:{color};margin-left:{50-bar_width:.1f}%;"
        else:
            bar_style = "width:1px;background:#6b7280;margin-left:50%;"
        rank_label = ""
        if i < 3:
            rank_label = f'<span style="color:#fbbf24;font-weight:bold"> TOP{i+1}</span>'
        elif i >= n - 3:
            rank_label = f'<span style="color:#60a5fa;font-weight:bold"> BOT{n-i}</span>'
        star = "⭐" if r["行业"] in active_names else ""
        cyc_key = _get_cycle_class(r["周期"])
        cc = CYCLE_COLORS[cyc_key]
        cyc_badge = (f'<span style="background:{cc["bg"]};color:{cc["text"]};'
                     f'padding:1px 6px;border-radius:8px;font-size:10px;margin-left:4px">{r["周期"]}</span>')
        pct_str = f"+{pct}%" if pct > 0 else f"{pct}%"
        pct_color = "#ef4444" if pct > 0 else ("#22c55e" if pct < 0 else "#9ca3af")
        bars_html += f"""<div style="display:flex;align-items:center;height:20px;margin:1px 0;font-size:11px">
            <div style="width:90px;text-align:right;padding-right:6px;white-space:nowrap;overflow:hidden;color:{'#fbbf24' if r['行业'] in active_names else '#d1d5db'}">{star}{r['行业']}</div>
            <div style="flex:1;position:relative;height:16px;background:#1a1a2e;border-radius:3px"><div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#374151"></div><div style="position:absolute;{bar_style}height:100%;border-radius:3px"></div></div>
            <div style="width:55px;text-align:right;padding-left:4px;color:{pct_color};font-weight:bold">{pct_str}</div>
            <div style="width:64px;text-align:left;padding-left:2px">{cyc_badge}</div>
            <div style="width:44px;font-size:10px">{rank_label}</div></div>"""
    return f"""<div style="background:#0d1117;border-radius:8px;padding:12px;margin-top:12px">
        <div style="font-size:12px;color:#8899aa;margin-bottom:8px;text-align:center">📊 31 行业涨跌幅排名 | {start.strftime('%m-%d')} → {end.strftime('%m-%d')} <span style="margin-left:15px;color:#ef4444">██ 上涨</span><span style="margin-left:8px;color:#22c55e">██ 下跌</span><span style="margin-left:8px;color:#fbbf24">⭐ 主线</span></div>
        {bars_html}</div>"""


def generate_annual_insights(phases, mainlines, switches, cycle_phases, year):
    insights = []
    if not mainlines:
        return insights
    industry_weeks = {}
    for ml in mainlines:
        industry_weeks[ml["行业"]] = industry_weeks.get(ml["行业"], 0) + ml["持续周数"]
    total_weeks = sum(industry_weeks.values())
    top3_industries = sorted(industry_weeks.items(), key=lambda x: x[1], reverse=True)[:3]
    top3_pct = sum(w for _, w in top3_industries) / total_weeks * 100 if total_weeks > 0 else 0
    top3_str = "、".join([f"{name}({weeks}周)" for name, weeks in top3_industries])
    insights.append({"title": f"🎯 主线集中度：TOP3 占比 {top3_pct:.1f}%",
                     "content": f"{year}年全年主线时间最集中于 {top3_str}。TOP3 行业占据主线总时间的 {top3_pct:.1f}%，"
                                f"{'集中度较高，市场风格偏极致' if top3_pct > 50 else '集中度适中，市场风格相对均衡'}。"})
    if switches:
        avg_gap = np.mean([abs(sw["间隔天数"]) for sw in switches])
        insights.append({"title": f"🔄 切换频率：全年 {len(switches)} 次，平均间隔 {avg_gap:.0f} 天",
                         "content": f"共识别 {len(switches)} 次主线切换，平均每 {avg_gap:.0f} 天一次。"
                                    f"{'频率较高，操作难度大' if avg_gap < 20 else '频率适中，调仓窗口充足'}。"})
    best = max(mainlines, key=lambda x: x["累计涨幅"])
    worst = min(mainlines, key=lambda x: x["累计涨幅"])
    insights.append({"title": f"💪 最强主线：{best['行业']} +{best['累计涨幅']}%（{best['持续周数']}周）",
                     "content": f"最强 {best['行业']} +{best['累计涨幅']}%（{best['持续周数']}周）；最弱 {worst['行业']}（{worst['累计涨幅']}%，{worst['持续周数']}周），差距 {best['累计涨幅'] - worst['累计涨幅']:.1f}pp。"})
    cycle_mainline = {}
    for ml in mainlines:
        cyc = cycle_phases.get(ml["行业"], "未标注")
        d = cycle_mainline.setdefault(cyc, {"count": 0, "total_return": 0})
        d["count"] += 1; d["total_return"] += ml["累计涨幅"]
    parts = []
    for cyc, data in sorted(cycle_mainline.items(), key=lambda x: x[1]["count"], reverse=True):
        avg_ret = data["total_return"] / data["count"] if data["count"] > 0 else 0
        parts.append(f"{cyc} {data['count']}次(均+{avg_ret:.1f}%)")
    insights.append({"title": "🔬 产能周期 × 主线关联",
                     "content": f"按周期阶段统计主线出现次数：{'，'.join(parts)}。景气向上行业更易成为主线。"})
    ferment_signals = [ml for ml in mainlines if ml.get("发酵期成交额变化", 0) > 20]
    if ferment_signals:
        avg_f = np.mean([ml["累计涨幅"] for ml in ferment_signals])
        insights.append({"title": f"📡 发酵信号：{len(ferment_signals)} 次成交额提前放量",
                         "content": f"{len(ferment_signals)} 条主线进入TOP3前成交额放量(>20%)，平均涨幅 +{avg_f:.1f}%，"
                                    f"{'成交额放量是有效领先指标' if avg_f > 5 else '差异不大'}。"})
    post_returns = [ml.get("退出后2周涨幅", 0) for ml in mainlines if "退出后2周涨幅" in ml]
    if post_returns:
        avg_post = np.mean(post_returns)
        neg_ratio = sum(1 for r in post_returns if r < 0) / len(post_returns) * 100
        insights.append({"title": f"📉 主线退出后：平均 {avg_post:+.1f}%，{neg_ratio:.0f}% 下跌",
                         "content": f"主线退出TOP3后两周平均 {avg_post:+.1f}%，{neg_ratio:.0f}%下跌。"
                                    f"{'退出信号是较好止盈时机' if neg_ratio > 60 else '部分退出后仍有惯性'}。"})
    return insights


def generate_html_report(phases, mainlines, switches, cross_sections, cycle_phases, industry_data=None, year=2025):
    css = """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
               background: #0a0e17; color: #e0e0e0; padding: 20px; }
        .header { text-align: center; padding: 40px 20px;
                  background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460);
                  border-radius: 16px; margin-bottom: 30px; }
        .header h1 { font-size: 32px; color: #00d4ff; margin-bottom: 10px; }
        .header p { font-size: 16px; color: #8899aa; }
        .summary-bar { display: flex; gap: 15px; flex-wrap: wrap;
                       margin-bottom: 30px; justify-content: center; }
        .summary-card { background: #151b2e; border-radius: 12px; padding: 20px;
                        min-width: 180px; text-align: center; border: 1px solid #2a3555; }
        .summary-card .number { font-size: 28px; font-weight: bold; color: #00d4ff; }
        .summary-card .label { font-size: 13px; color: #8899aa; margin-top: 5px; }
        .phase-card { background: #111827; border-radius: 12px; margin-bottom: 25px; overflow: hidden;
                      border: 1px solid #1f2937; }
        .phase-header { padding: 20px 25px; background: linear-gradient(90deg, #1a2332, #1f2d40);
                        border-bottom: 1px solid #2a3555; display: flex; justify-content: space-between; align-items: center; }
        .phase-title { font-size: 20px; font-weight: bold; }
        .phase-dates { font-size: 14px; color: #8899aa; }
        .phase-body { padding: 20px 25px; }
        .mainline-tag { display: inline-block; padding: 6px 14px; border-radius: 20px; margin: 3px; font-size: 13px; font-weight: bold; }
        .mainline-tag.active { background: #064e3b; color: #34d399; border: 1px solid #059669; }
        .mainline-tag.fading { background: #4c1d1d; color: #f87171; border: 1px solid #dc2626; }
        .mainline-tag.rising { background: #1e3a5f; color: #60a5fa; border: 1px solid #3b82f6; }
        .catalyst-item { background: #1a2332; padding: 8px 15px; border-radius: 8px; margin: 5px 0; font-size: 13px; border-left: 3px solid #f59e0b; }
        .cycle-tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin: 2px; }
        .cycle-tag.growth { background: #064e3b; color: #34d399; }
        .cycle-tag.peak { background: #78350f; color: #fbbf24; }
        .cycle-tag.excess { background: #4c1d1d; color: #f87171; }
        .cycle-tag.clearance { background: #312e81; color: #a78bfa; }
        .cycle-tag.recovery { background: #1e3a5f; color: #60a5fa; }
        .cycle-tag.stable { background: #1f2937; color: #9ca3af; }
        .cycle-tag.unknown { background: #1f2937; color: #6b7280; }
        .snapshot-table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 12px; }
        .snapshot-table th { background: #1a2332; padding: 8px 10px; text-align: left; color: #8899aa; border-bottom: 1px solid #2a3555; position: sticky; top: 0; }
        .snapshot-table td { padding: 6px 10px; border-bottom: 1px solid #1f2937; }
        .snapshot-table tr:hover { background: #1a2332; }
        .positive { color: #ef4444; } .negative { color: #22c55e; }
        .section-title { font-size: 22px; font-weight: bold; color: #00d4ff; margin: 30px 0 15px; padding-left: 15px; border-left: 4px solid #00d4ff; }
        .insight-box { background: #1a2332; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #2a3555; }
        .insight-box h3 { color: #fbbf24; margin-bottom: 10px; font-size: 16px; }
        .insight-box p { font-size: 14px; line-height: 1.8; color: #d1d5db; }
        .regime-badge { padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; }
        .regime-bull { background: #7f1d1d; color: #fca5a5; }
        .regime-bear { background: #064e3b; color: #6ee7b7; }
        .regime-neutral { background: #1f2937; color: #9ca3af; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        @media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } .summary-bar { flex-direction: column; } }
        .lifecycle-bar { display: flex; height: 24px; border-radius: 6px; overflow: hidden; margin: 8px 0; }
        .lifecycle-seg { display: flex; align-items: center; justify-content: center; font-size: 11px; color: white; font-weight: bold; }
        .lifecycle-seg.ferment { background: #3b82f6; }
        .lifecycle-seg.accel { background: #ef4444; }
        .lifecycle-seg.peak-seg { background: #f59e0b; }
        .lifecycle-seg.decline { background: #6b7280; }
        .switch-arrow { font-size: 24px; color: #f59e0b; margin: 0 10px; }
        .switch-box { background: #1a2332; border-radius: 10px; padding: 15px; margin: 10px 0; border: 1px solid #2a3555; }
        .switch-from { color: #f87171; font-weight: bold; }
        .switch-to { color: #34d399; font-weight: bold; }
        .cycle-dist { display: flex; flex-wrap: wrap; gap: 8px; margin: 15px 0; }
        .cycle-dist-item { padding: 8px 12px; border-radius: 8px; font-size: 13px; text-align: center; }
        .collapsible { cursor: pointer; }
        .collapsible-content { display: none; }
        .collapsible-content.show { display: block; }
    </style>
    <script>
    function toggleContent(id) {{
        var el = document.getElementById(id);
        if (el) el.classList.toggle('show');
    }}
    </script>
    """
    total_mainlines = len(mainlines)
    total_switches = len(switches)
    total_phases = len(phases)
    best_str = f"{max(mainlines, key=lambda x: x['累计涨幅'])['行业']} +{max(mainlines, key=lambda x: x['累计涨幅'])['累计涨幅']}%" if mainlines else "-"
    unique_industries = set(ml["行业"] for ml in mainlines)

    summary_html = f"""
    <div class="summary-bar">
        <div class="summary-card"><div class="number">{total_phases}</div><div class="label">市场阶段</div></div>
        <div class="summary-card"><div class="number">{total_mainlines}</div><div class="label">主线段落</div></div>
        <div class="summary-card"><div class="number">{total_switches}</div><div class="label">主线切换</div></div>
        <div class="summary-card"><div class="number">{len(unique_industries)}</div><div class="label">涉及行业</div></div>
        <div class="summary-card"><div class="number" style="font-size:20px">{best_str}</div><div class="label">最强主线</div></div>
        <div class="summary-card"><div class="number">{len([c for c in cycle_phases.values() if c != '未标注'])}/31</div><div class="label">周期已标注</div></div>
    </div>"""

    # 31行业产能周期全景分布
    cycle_dist = {}
    for ind in SW31_INDUSTRIES.values():
        cyc = cycle_phases.get(ind, "未标注")
        cycle_dist.setdefault(cyc, []).append(ind)
    cycle_dist_html = ""
    for cyc in ["成长期", "景气顶部", "复苏期", "成熟稳定期", "过剩期", "出清期", "未标注"]:
        if cyc not in cycle_dist:
            continue
        inds = cycle_dist[cyc]
        cc = CYCLE_COLORS.get(_get_cycle_class(cyc), CYCLE_COLORS["未标注"])
        cycle_dist_html += (f'<div class="cycle-dist-item" style="background:{cc["bg"]};color:{cc["text"]};'
                            f'border:1px solid {cc["border"]}"><strong>{cyc}</strong> ({len(inds)})<br>'
                            f'<span style="font-size:11px">{", ".join(inds)}</span></div>')
    cycle_dist_section = f'<div class="section-title">🔄 31 行业产能周期全景</div><div class="cycle-dist">{cycle_dist_html}</div>'

    cycle_class_map = {"成长期": "growth", "景气顶部": "peak", "过剩期": "excess",
                       "出清期": "clearance", "复苏期": "recovery", "成熟稳定期": "stable"}
    phase_cards = ""
    for phase in phases:
        start_str = phase["开始日期"].strftime("%Y-%m-%d")
        end_str = phase["结束日期"].strftime("%Y-%m-%d")
        regime = phase["大盘状态"]
        regime_class = "regime-bull" if ("牛" in regime or "偏多" in regime) else ("regime-bear" if ("熊" in regime or "偏空" in regime) else "regime-neutral")
        mainline_tags = ""
        for ml in phase["活跃主线"]:
            tag_class = "rising" if ml["累计涨幅"] > 10 else ("fading" if ml["累计涨幅"] < 0 else "active")
            mainline_tags += f'<span class="mainline-tag {tag_class}">{ml["行业"]} {"+" if ml["累计涨幅"]>0 else ""}{ml["累计涨幅"]}% ({ml["持续周数"]}周)</span>'
        if not mainline_tags:
            mainline_tags = '<span style="color:#6b7280">无明确主线（震荡/普涨/普跌）</span>'
        catalyst_html = ""
        for cat in phase["催化剂"]:
            catalyst_html += f'<div class="catalyst-item"><strong>{cat["日期"]}</strong> {cat["事件"]} <span style="color:#6b7280">({cat["类型"]})</span> → {cat["关联行业"]}</div>'
        if not catalyst_html:
            catalyst_html = '<div style="color:#6b7280;font-size:13px">本阶段无重大催化剂记录</div>'
        cycle_html = ""
        for ind, cyc in phase["产能周期"].items():
            cc = "unknown"
            for key, val in cycle_class_map.items():
                if key in str(cyc):
                    cc = val; break
            cycle_html += f'<span class="cycle-tag {cc}">{ind}: {cyc}</span> '
        if not cycle_html:
            cycle_html = '<span style="color:#6b7280;font-size:12px">无周期标签</span>'
        lifecycle_html = ""
        for ml in phase["活跃主线"]:
            ferment_pct = ml.get("发酵期成交额变化", 0)
            to_peak = ml.get("起点到顶峰涨幅", 0)
            from_peak = ml.get("顶峰到结束跌幅", 0)
            total = abs(to_peak) + abs(from_peak) + 10
            accel_w = max(int(abs(to_peak) / total * 100), 5)
            decline_w = max(int(abs(from_peak) / total * 100), 5)
            ferment_w, peak_w = 15, 5
            peak_date_str = pd.Timestamp(ml["顶峰日期"]).strftime("%m-%d") if ml.get("顶峰日期") is not None else ""
            lifecycle_html += f"""<div style="margin:8px 0"><div style="font-size:13px;margin-bottom:4px"><strong>{ml['行业']}</strong> 发酵量变 {'+' if ferment_pct>0 else ''}{ferment_pct}% → 加速 +{to_peak}% → 顶峰 {peak_date_str} → 回落 {from_peak}% → 退出后 {ml.get('退出后2周涨幅', 0)}%</div>
            <div class="lifecycle-bar"><div class="lifecycle-seg ferment" style="width:{ferment_w}%">发酵</div><div class="lifecycle-seg accel" style="width:{accel_w}%">+{to_peak}%</div><div class="lifecycle-seg peak-seg" style="width:{peak_w}%">峰</div><div class="lifecycle-seg decline" style="width:{decline_w}%">{from_peak}%</div></div></div>"""
        active_names = [ml["行业"] for ml in phase["活跃主线"]]
        title_suffix = " × ".join(active_names[:3]) if active_names else "震荡整理"
        phase_id = f"phase_{phase['阶段序号']}"
        mini_bar = generate_mini_bar_chart_html(phase, industry_data, cycle_phases) if industry_data else ""
        # 迷你图折叠区(预拼为普通字符串，避免 f-string 反斜杠限制)
        if mini_bar:
            mini_section = ('<div class="collapsible" onclick="toggleContent(\'' + phase_id + '_bars\')">'
                            '<h4 style="color:#00d4ff;margin-top:15px">▶ 点击展开 31 行业涨跌幅排名</h4></div>'
                            '<div id="' + phase_id + '_bars" class="collapsible-content">' + mini_bar + '</div>')
        else:
            mini_section = ""
        phase_cards += f"""
        <div class="phase-card">
            <div class="phase-header">
                <div><span class="phase-title">阶段 {phase['阶段序号']}：{title_suffix}</span>
                <span class="phase-dates" style="margin-left:15px">{start_str} → {end_str}（{phase['持续天数']} 天）</span></div>
                <span class="regime-badge {regime_class}">{regime} ({phase['大盘均涨幅']}%)</span>
            </div>
            <div class="phase-body"><div class="grid-2">
                <div><h4 style="color:#8899aa;margin-bottom:8px">📌 活跃主线</h4>{mainline_tags}
                    <h4 style="color:#8899aa;margin:15px 0 8px">📊 生命周期</h4>{lifecycle_html if lifecycle_html else '<span style="color:#6b7280">-</span>'}</div>
                <div><h4 style="color:#8899aa;margin-bottom:8px">⚡ 催化剂</h4>{catalyst_html}
                    <h4 style="color:#8899aa;margin:15px 0 8px">🔄 产能周期</h4>{cycle_html}</div>
            </div>
            {mini_section}
            </div>
        </div>"""

    switch_html = ""
    for sw in switches:
        sw_date = pd.Timestamp(sw["切换日期"]).strftime("%Y-%m-%d")
        switch_html += f"""<div class="switch-box"><div style="display:flex;align-items:center;flex-wrap:wrap">
            <span style="color:#8899aa;margin-right:15px">{sw_date}</span>
            <span class="switch-from">{sw['退出主线']} (+{sw['退出主线累计涨幅']}%, {sw['退出主线持续周数']}周)</span>
            <span class="switch-arrow">→</span>
            <span class="switch-to">{sw['新主线']} (+{sw['新主线累计涨幅']}%, {sw['新主线持续周数']}周)</span>
            <span style="color:#6b7280;margin-left:15px">间隔 {sw['间隔天数']} 天</span></div></div>"""

    snapshot_html = ""
    for cs in cross_sections[:8]:
        sw_date_str = cs["切换日期"]
        table_rows = ""
        for i, row in enumerate(cs["快照"][:31]):
            ret_pre_class = "positive" if row["切换前涨跌幅"] > 0 else "negative"
            ret_post_class = "positive" if row["切换后涨跌幅"] > 0 else "negative"
            amt_class = "positive" if row["成交额变化"] > 0 else "negative"
            bg = "background:#1a2332;" if i < 3 else ""
            table_rows += f'<tr style="{bg}"><td>{i+1}</td><td><strong>{row["行业"]}</strong></td><td class="{ret_pre_class}">{row["切换前涨跌幅"]}%</td><td class="{ret_post_class}">{row["切换后涨跌幅"]}%</td><td class="{amt_class}">{row["成交额变化"]}%</td><td>{row["动向"]}</td></tr>'
        snapshot_html += f"""<div style="margin-bottom:20px"><h4 style="color:#f59e0b;margin-bottom:10px">📸 {sw_date_str} 切换横截面（按切换后涨幅排序）</h4><div style="max-height:400px;overflow-y:auto"><table class="snapshot-table"><thead><tr><th>#</th><th>行业</th><th>切换前1周</th><th>切换后1周</th><th>成交额变化</th><th>动向</th></tr></thead><tbody>{table_rows}</tbody></table></div></div>"""

    insights = generate_annual_insights(phases, mainlines, switches, cycle_phases, year)
    insights_html = ""
    for ins in insights:
        insights_html += f'<div class="insight-box"><h3>{ins["title"]}</h3><p>{ins["content"]}</p></div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{year} 年 A 股主线演变全景报告</title>{css}</head>
<body>
    <div class="header"><h1>🔥 {year} 年 A 股主线演变全景报告</h1>
        <p>基于 31 个申万一级行业日线数据 · 自动识别主线切换 · 生命周期追踪 · 产能周期叠加</p>
        <p style="margin-top:8px;color:#6b7280">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据范围: {year}-01-01 ~ {year}-12-31</p></div>
    {summary_html}
    {cycle_dist_section}
    <div class="section-title">📊 年度总结洞察</div>{insights_html}
    <div class="section-title">📅 阶段演变时间轴（合并后）</div>{phase_cards}
    <div class="section-title">🔄 主线切换事件</div>{switch_html if switch_html else '<p style="color:#6b7280">无切换事件</p>'}
    <div class="section-title">📸 切换点横截面快照</div>{snapshot_html if snapshot_html else '<p style="color:#6b7280">无快照数据</p>'}
</body></html>"""
    return html


# ══════════════════════════════════════════════════════
#  修复补丁：主线评分体系 + 年度真实主线识别
# ══════════════════════════════════════════════════════
def calc_annual_industry_returns(industry_data, year):
    """计算每个行业的年度全年涨跌幅(年初首交易日→年末末交易日)"""
    results = {}
    for name, df in industry_data.items():
        df = df[df["日期"].dt.year == year].sort_values("日期")
        if len(df) >= 2:
            first_close = df["收盘"].iloc[0]
            last_close = df["收盘"].iloc[-1]
            results[name] = round((last_close / first_close - 1) * 100, 2) if first_close > 0 else 0
        else:
            results[name] = 0
    return results


def calc_mainline_score(mainline, annual_returns):
    """
    主线综合评分 v3(配合容间断识别)
    = 累计涨幅×0.25 + 持续周数×0.30 + 成交额占比×0.20 + 全年涨幅一致性×0.15 + 活跃率×0.10 + 惩罚

    权重调整:降低累计涨幅权重(避免短期爆发主导),提高持续周数权重(奖励持续性),
    新增活跃率维度(奖励高紧凑度主线),短期爆发惩罚保留。
    """
    cum_return = mainline.get("累计涨幅", 0)
    weeks = mainline.get("持续周数", 0)
    amount_share = mainline.get("平均成交额占比", 0)
    industry = mainline.get("行业", "")
    activity_rate = mainline.get("活跃率", 1.0)  # 新增:容间断主线的紧凑度(0~1)

    return_score = min(abs(cum_return) / 50, 1.0) * (1 if cum_return > 0 else -0.5)
    weeks_score = min(weeks / 15, 1.0)
    amount_score = min(amount_share / 8, 1.0)
    activity_score = max(0.0, min(activity_rate, 1.0))

    annual_ret = annual_returns.get(industry, 0)
    # 用稳健排名(避免相同值.index()错位): 比该值大的个数+1
    sorted_vals = sorted(annual_returns.values(), reverse=True)
    rank = 1
    for v in sorted_vals:
        if v > annual_ret:
            rank += 1
        else:
            break
    total = len(sorted_vals) if sorted_vals else 1
    if rank <= total * 0.2:
        consistency_score = 1.0
    elif rank <= total * 0.5:
        consistency_score = 0.5
    else:
        consistency_score = 0.0

    brevity_penalty = -0.3 if (weeks <= 2 and abs(cum_return) > 30) else 0
    # 活跃率过低(间断过多)额外惩罚
    low_activity_penalty = -0.1 if activity_rate < 0.6 else 0

    score = (return_score * 0.25 + weeks_score * 0.30 + amount_score * 0.20
             + consistency_score * 0.15 + activity_score * 0.10
             + brevity_penalty + low_activity_penalty)
    return round(score, 3)


def identify_annual_true_mainlines(mainlines, annual_returns, top_n=5):
    """识别年度真实主线: 评分→按行业聚合→全年涨幅兜底校验"""
    for ml in mainlines:
        ml["综合评分"] = calc_mainline_score(ml, annual_returns)

    industry_agg = {}
    for ml in mainlines:
        ind = ml["行业"]
        agg = industry_agg.setdefault(ind, {"总周数": 0, "最大单段涨幅": 0,
                                            "最高评分": 0, "段数": 0, "评分合计": 0})
        agg["总周数"] += ml.get("持续周数", 0)
        agg["最大单段涨幅"] = max(agg["最大单段涨幅"], ml.get("累计涨幅", 0))
        agg["最高评分"] = max(agg["最高评分"], ml.get("综合评分", 0))
        agg["段数"] += 1
        agg["评分合计"] += ml.get("综合评分", 0)

    ranking = []
    for ind, agg in industry_agg.items():
        annual_ret = annual_returns.get(ind, 0)
        max_annual = max((abs(v) for v in annual_returns.values()), default=1) or 1
        annual_norm = annual_ret / max_annual if max_annual > 0 else 0
        combined = agg["评分合计"] * 0.6 + annual_norm * 0.4
        ranking.append((ind, round(combined, 3), annual_ret,
                        agg["最大单段涨幅"], agg["总周数"], agg["段数"]))
    ranking.sort(key=lambda x: x[1], reverse=True)

    # 兜底校验: 评分TOP5 与 全年涨幅TOP5 严重不一致(重叠<3)则混合
    annual_top5_names = set(name for name, _ in sorted(annual_returns.items(),
                                                       key=lambda x: x[1], reverse=True)[:5])
    score_top5_names = set(r[0] for r in ranking[:5])
    missing = annual_top5_names - score_top5_names
    if len(missing) >= 3:
        new_ranking = ranking[:2]
        for name in missing:
            new_ranking.append((name, 0, annual_returns[name], 0, 0, 0))
        for r in ranking[2:]:
            if r[0] not in [nr[0] for nr in new_ranking]:
                new_ranking.append(r)
        ranking = new_ranking

    return ranking[:top_n]


def get_year_true_best(mainlines, annual_returns):
    """返回年度真实最强主线(单个行业): (行业, 全年涨幅, 最大单段涨幅, 总周数)"""
    ranking = identify_annual_true_mainlines(mainlines, annual_returns, top_n=5)
    if not ranking:
        if annual_returns:
            best = max(annual_returns.items(), key=lambda x: x[1])
            return best[0], best[1], 0, 0
        return "-", 0, 0, 0
    top = ranking[0]
    return top[0], top[2], top[3], top[4]


def generate_annual_mainline_report(year=2025):
    print(f"\n{'='*60}\n  {year} 年 A 股主线演变全景报告生成器\n  基于 31 个申万一级行业\n{'='*60}\n")
    print("[1/7] 加载 31 行业日线数据...")
    industry_data, raw_df = load_sw31_data(year)
    print(f"  ✓ 已加载 {len(industry_data)} 个行业，共 {len(raw_df)} 行")
    print("[2/7] 加载催化剂事件库...")
    catalysts = load_catalysts(year)
    print(f"  ✓ {year}年催化剂事件 {len(catalysts)} 条")
    print("[3/7] 加载产能周期标签...")
    cycle_phases = load_cycle_phases()
    print(f"  ✓ 已标注 {len(cycle_phases)} 个行业")
    for ind in sorted(SW31_INDUSTRIES.values()):
        if ind not in cycle_phases:
            cycle_phases[ind] = "未标注"
    print("[4/7] 计算周度涨跌幅与成交额占比...")
    weekly_df = calc_weekly_metrics(industry_data, year)
    n_weeks = weekly_df[["年", "周"]].drop_duplicates().shape[0]
    print(f"  ✓ {n_weeks} 个交易周，{len(weekly_df)} 行周度记录")
    print("[5/7] 识别主线段落与切换节点...")
    mainlines = identify_mainlines(weekly_df, top_n=3, min_weeks=2)
    for i in range(len(mainlines)):
        mainlines[i] = analyze_lifecycle(mainlines[i], industry_data, year)
    switches = detect_switch_points(mainlines)
    print(f"  ✓ {len(mainlines)} 段主线，{len(switches)} 次切换")
    print(f"  涉及行业: {len(set(ml['行业'] for ml in mainlines))} 个")
    if mainlines:
        best = max(mainlines, key=lambda x: x["累计涨幅"])
        print(f"  最强主线: {best['行业']} +{best['累计涨幅']}% ({best['持续周数']}周)")
    print("[6/7] 生成阶段划分与横截面快照...")
    raw_phases = segment_phases(mainlines, switches, industry_data, catalysts, cycle_phases, year)
    phases = merge_phases(raw_phases)
    print(f"  ✓ 细粒度 {len(raw_phases)} 段 → 合并后 {len(phases)} 段")
    cross_sections = []
    for sw in switches:
        sw_date = pd.Timestamp(sw["切换日期"])
        snapshot = generate_cross_section(sw_date, weekly_df, industry_data)
        cross_sections.append({"切换日期": sw_date.strftime("%Y-%m-%d"),
                               "退出": sw["退出主线"], "进入": sw["新主线"], "快照": snapshot})
    print(f"  ✓ {len(phases)} 个阶段，{len(cross_sections)} 个横截面快照")
    print("[7/7] 生成 HTML 报告与 CSV...")
    html = generate_html_report(phases, mainlines, switches, cross_sections, cycle_phases, industry_data, year)
    html_path = REPORT_DIR / f"{year}_mainline_evolution.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ HTML 报告: {html_path} ({os.path.getsize(html_path)/1024:.0f} KB)")
    ml_df = pd.DataFrame(mainlines)
    if "周涨跌幅序列" in ml_df.columns:
        ml_df["周涨跌幅序列"] = ml_df["周涨跌幅序列"].apply(str)
    ml_csv = RAW_DIR / f"{year}_mainline_periods.csv"
    ml_df.to_csv(ml_csv, index=False, encoding="utf-8-sig")
    print(f"  ✓ 主线段落 CSV: {ml_csv}")
    sw_df = pd.DataFrame(switches)
    sw_df.to_csv(RAW_DIR / f"{year}_mainline_switches.csv", index=False, encoding="utf-8-sig")
    cs_records = []
    for cs in cross_sections:
        for row in cs["快照"]:
            cs_records.append({"切换日期": cs["切换日期"], "退出主线": cs["退出"],
                               "进入主线": cs["进入"], **row})
    pd.DataFrame(cs_records).to_csv(RAW_DIR / f"{year}_switch_cross_sections.csv", index=False, encoding="utf-8-sig")
    phase_records = []
    for p in phases:
        phase_records.append({"阶段": p["阶段序号"], "开始": p["开始日期"].strftime("%Y-%m-%d"),
                              "结束": p["结束日期"].strftime("%Y-%m-%d"), "天数": p["持续天数"],
                              "大盘状态": p["大盘状态"], "大盘均涨幅": p["大盘均涨幅"],
                              "活跃主线": ", ".join([ml["行业"] for ml in p["活跃主线"]]),
                              "催化剂": "; ".join([c["事件"] for c in p["催化剂"]]),
                              "产能周期": str(p["产能周期"])})
    pd.DataFrame(phase_records).to_csv(RAW_DIR / f"{year}_phases.csv", index=False, encoding="utf-8-sig")
    print(f"  ✓ 切换事件/横截面/阶段 CSV 已保存")

    print(f"\n{'='*60}\n  {year} 年主线演变摘要\n{'='*60}")
    for p in phases:
        active_str = ", ".join([f"{ml['行业']}(+{ml['累计涨幅']}%)" for ml in p["活跃主线"]]) or "无明确主线"
        cat_str = ", ".join([c["事件"][:15] for c in p["催化剂"][:2]]) or "-"
        print(f"\n  阶段 {p['阶段序号']} | {p['开始日期'].strftime('%m-%d')} → {p['结束日期'].strftime('%m-%d')} ({p['持续天数']}天) | {p['大盘状态']}")
        print(f"    主线: {active_str}")
        print(f"    催化剂: {cat_str}")
    print(f"\n  主线切换事件 TOP5:")
    for sw in switches[:5]:
        print(f"    {pd.Timestamp(sw['切换日期']).strftime('%m-%d')} {sw['退出主线']} → {sw['新主线']} (间隔{sw['间隔天数']}天)")
    print(f"\n{'='*60}\n  报告已保存至 {REPORT_DIR}\n{'='*60}\n")
    return {"phases": phases, "mainlines": mainlines, "switches": switches, "cross_sections": cross_sections}


if __name__ == "__main__":
    year = 2025
    if len(sys.argv) > 1:
        try:
            year = int(sys.argv[1])
        except ValueError:
            pass
    generate_annual_mainline_report(year)
