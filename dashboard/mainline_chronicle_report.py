#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主线编年史报告生成器
====================
逐年、逐段叙事式主线演变报告。

数据源(均为已生成的真实文件,无算法重算):
  - raw_data/{y1}_{y2}_mainlines_v3.csv   主线段落(含级别/活跃率/日期)
  - raw_data/{y1}_{y2}_switch_signals.csv 切换记录(见顶/发酵/交叉窗口信号嵌于一条记录)
  - raw_data/catalyst_events_full.csv     催化事件(中文列,2015至今)
  - raw_data/sw31_cycle_phases.csv        31行业产能周期阶段

报告结构:
  每年一个章节 → 主线时间轴(节点=主线段落)→ 节点间切换分析框
  (三栏:旧主线见顶信号 | 交叉窗口 | 新主线发酵信号)→ 年度小结
  末尾跨年纵向分析:行业×年份矩阵 + 反复出现的切换模式。
"""

import os
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw_data")
REPORT_DIR = os.path.join(BASE_DIR, "dashboard", "replay_reports")
os.makedirs(REPORT_DIR, exist_ok=True)

# 行业大类
_SECTOR_GROUP = {
    "电子": "TMT", "计算机": "TMT", "通信": "TMT", "传媒": "TMT",
    "电力设备": "制造", "机械设备": "制造", "国防军工": "制造", "汽车": "制造",
    "食品饮料": "消费", "医药生物": "消费", "家用电器": "消费", "美容护理": "消费",
    "商贸零售": "消费", "社会服务": "消费", "纺织服饰": "消费", "轻工制造": "消费",
    "农林牧渔": "消费",
    "有色金属": "周期", "煤炭": "周期", "石油石化": "周期", "钢铁": "周期",
    "基础化工": "周期", "建筑材料": "周期", "建筑装饰": "周期",
    "银行": "金融", "非银金融": "金融", "房地产": "金融",
    "公用事业": "其他", "环保": "其他", "交通运输": "其他", "综合": "其他",
}

# 年度时代标签:(名称, 颜色, 背景描述)
_ERA_LABELS = {
    2016: ("供给侧改革", "#e67e22", "去产能+PPP+房地产去库存"),
    2017: ("核心资产崛起", "#2ecc71", "外资流入+消费升级+供给侧红利"),
    2018: ("去杠杆熊市", "#e74c3c", "中美贸易战+金融去杠杆+全面下跌"),
    2019: ("科技牛启动", "#3498db", "5G商用+半导体国产替代+科创板"),
    2020: ("疫情与流动性", "#9b59b6", "COVID-19+全球放水+消费反弹"),
    2021: ("碳中和新能源", "#1abc9c", "双碳政策+锂电光伏+周期涨价"),
    2022: ("地缘与衰退", "#e74c3c", "俄乌冲突+美联储加息+地产暴雷"),
    2023: ("AI元年", "#3498db", "ChatGPT+算力需求+TMT全面爆发"),
    2024: ("AI深化+924行情", "#f39c12", "AI应用+高股息+政策反转"),
    2025: ("AI应用落地", "#2ecc71", "DeepSeek+机器人+关税冲击+有色金属"),
}

_LEVEL_COLORS = {"长期主线": "#f1c40f", "中期主线": "#3498db", "短期热点": "#7f8c8d"}
_GROUP_COLORS = {"TMT": "#3498db", "制造": "#e67e22", "消费": "#2ecc71",
                 "周期": "#e74c3c", "金融": "#f1c40f", "其他": "#95a5a6"}


def _hex_rgb(h):
    h = h.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def _score_cls(score):
    if score >= 3:
        return "sb-high"
    if score >= 2:
        return "sb-med"
    return "sb-low"


def _safe_ts(s):
    """把日期列安全转为 Timestamp,失败返回 NaT。"""
    try:
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.NaT


# ── 逐周明细数据层 ──────────────────────────────────────
_WEEKLY_CACHE = {}  # {(year): DataFrame}, 缓存每年聚合周线


def _load_weekly_detail(year):
    """从 sw31_daily_all.csv 聚合该年全部行业全部周的周线(含间断周)。

    返回 DataFrame,列:行业名称, 周, 周涨跌幅, 周成交额(亿), 周排名, 累计涨幅
    累计涨幅 = 从该年第一周到当前周的连乘(按该行业每周涨跌幅)。
    """
    if year in _WEEKLY_CACHE:
        return _WEEKLY_CACHE[year]
    path = os.path.join(RAW_DIR, "sw31_daily_all.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    d = pd.read_csv(path)
    d["日期"] = pd.to_datetime(d["日期"], errors="coerce")
    d = d[d["日期"].dt.year == year].copy()
    if d.empty:
        _WEEKLY_CACHE[year] = d
        return d
    d["周"] = d["日期"].dt.isocalendar().week.astype(int)
    g = d.groupby(["行业名称", "周"]).agg(
        周开盘=("开盘", "first"), 周收盘=("收盘", "last"),
        周成交额=("成交额_亿元", "sum")).reset_index()
    g["周涨跌幅"] = np.where(g["周开盘"] > 0,
                            (g["周收盘"] / g["周开盘"] - 1) * 100, 0)
    g["周排名"] = g.groupby("周")["周涨跌幅"].rank(ascending=False, method="min").astype(int)
    # 累计涨幅(按周序连乘)
    g = g.sort_values(["行业名称", "周"])
    g["cum"] = (1 + g["周涨跌幅"] / 100).groupby(g["行业名称"]).cumprod()
    g["累计涨幅"] = (g["cum"] - 1) * 100
    g.drop(columns=["cum", "周开盘", "周收盘"], inplace=True)
    _WEEKLY_CACHE[year] = g
    return g


def _weekly_for_mainline(wk_df, ind, start_w, end_w, active_weeks, bear_weeks=None):
    """取某行业 start_w~end_w 全周序列(含间断),标注是否活跃。

    返回 list[dict]: {周, 周涨跌幅, 累计涨幅, 周成交额, 周排名, 活跃, 阶段, 熊市周}
    间断周(不在 active_weeks)若无数据则补一行占位。
    阶段判定:启动要求涨幅>0(涨幅<0的活跃周标"伪启动",不计入生命周期);
              熊市周(全市场普跌)单独标记。
    """
    if wk_df.empty:
        return []
    bear_set = set(bear_weeks or [])
    sub = wk_df[(wk_df["行业名称"] == ind) &
                (wk_df["周"] >= start_w) & (wk_df["周"] <= end_w)].sort_values("周")
    active_set = set(active_weeks)
    rows = []
    prev_ret = None
    prev_amt = None
    prev_rank = None
    peak_ret = sub["周涨跌幅"].max() if not sub.empty else 0
    peak_amt = sub["周成交额"].max() if not sub.empty else 0
    active_seq = [r for r in range(start_w, end_w + 1)]
    sub_map = {int(r["周"]): r for _, r in sub.iterrows()}
    first_active_seen = False
    active_count_so_far = 0  # 真正计入生命周期的活跃周数(排除伪启动)
    for w in active_seq:
        r = sub_map.get(w)
        is_active = w in active_set
        is_bear = w in bear_set
        if r is None:
            # 间断且无数据
            rows.append({"周": w, "周涨跌幅": None, "累计涨幅": None,
                         "周成交额": None, "周排名": None, "活跃": False,
                         "阶段": "间断", "熊市周": False})
            continue
        ret = float(r["周涨跌幅"]); amt = float(r["周成交额"]); rank = int(r["周排名"])
        cum = float(r["累计涨幅"])
        # 阶段判定
        if not is_active:
            stage = "间断"
        elif active_count_so_far < 2 and is_active:
            # 启动阶段:要求涨幅>0;涨幅<0 标"伪启动"(不计入生命周期)
            if ret > 0:
                stage = "启动"
                active_count_so_far += 1
            else:
                stage = "伪启动"
        elif (ret == peak_ret and peak_ret > 0) or (amt == peak_amt and amt > 0):
            stage = "高潮"
            active_count_so_far += 1
        elif prev_ret is not None and (ret < prev_ret or (prev_amt and amt < prev_amt)):
            if ret < 0 or rank > 5:
                stage = "衰退"
            else:
                stage = "放缓"
            active_count_so_far += 1
        elif ret < 0 or rank > 5:
            stage = "衰退"
            active_count_so_far += 1
        else:
            stage = "加速"
            active_count_so_far += 1
        rows.append({"周": w, "周涨跌幅": ret, "累计涨幅": cum,
                     "周成交额": amt, "周排名": rank, "活跃": is_active,
                     "阶段": stage, "熊市周": is_bear})
        prev_ret, prev_amt, prev_rank = ret, amt, rank
    return rows


def _mini_svg(rows, width=400, height=120):
    """纯 SVG 迷你图:周涨跌幅折线 + 成交额柱 + 高潮星/衰退三角。"""
    pts = [r for r in rows if r["周涨跌幅"] is not None]
    if len(pts) < 2:
        return '<div style="color:var(--text3);font-size:12px;padding:8px;">数据不足</div>'
    n = len(pts)
    rets = [r["周涨跌幅"] for r in pts]
    amts = [r["周成交额"] for r in pts]
    rmin, rmax = min(rets + [0]), max(rets + [0])
    amax = max(amts) if max(amts) > 0 else 1
    pad_l, pad_r, pad_t, pad_b = 28, 28, 10, 16
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b
    x_at = lambda i: pad_l + (i / max(n - 1, 1)) * pw
    y_ret = lambda v: pad_t + (1 - (v - rmin) / (rmax - rmin if rmax != rmin else 1)) * ph
    y_amt = lambda v: pad_t + ph - (v / amax) * (ph * 0.6)  # 柱占下方60%
    zero_y = y_ret(0)
    peak_idx = rets.index(max(rets))
    # 衰退起点:首个涨幅转负且之前有正
    decl_idx = None
    for i in range(1, n):
        if rets[i] < 0 and rets[i - 1] > 0:
            decl_idx = i
            break
    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:{width}px;">']
    # 成交额柱
    for i, a in enumerate(amts):
        bx = x_at(i) - 3
        bh = (a / amax) * (ph * 0.6)
        svg.append(f'<rect x="{bx:.1f}" y="{(pad_t+ph-bh):.1f}" width="6" height="{bh:.1f}" fill="#3a4660" opacity="0.5"/>')
    # 零轴
    svg.append(f'<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width-pad_r}" y2="{zero_y:.1f}" stroke="#2a3555" stroke-width="0.5" stroke-dasharray="2,2"/>')
    # 涨跌幅折线
    line_pts = " ".join(f"{x_at(i):.1f},{y_ret(rets[i]):.1f}" for i in range(n))
    svg.append(f'<polyline points="{line_pts}" fill="none" stroke="#f1c40f" stroke-width="1.5"/>')
    # 数据点
    for i in range(n):
        col = "#e74c3c" if rets[i] >= 0 else "#2ecc71"
        svg.append(f'<circle cx="{x_at(i):.1f}" cy="{y_ret(rets[i]):.1f}" r="1.8" fill="{col}"/>')
    # 高潮星
    px, py = x_at(peak_idx), y_ret(rets[peak_idx])
    svg.append(f'<text x="{px:.1f}" y="{(py-5):.1f}" fill="#f1c40f" font-size="11" text-anchor="middle">★</text>')
    # 衰退三角
    if decl_idx is not None:
        dx, dy = x_at(decl_idx), y_ret(rets[decl_idx])
        svg.append(f'<text x="{dx:.1f}" y="{(dy-5):.1f}" fill="#e74c3c" font-size="10" text-anchor="middle">▼</text>')
    # 轴标签
    svg.append(f'<text x="4" y="{pad_t+8:.0f}" fill="#8892a4" font-size="9">{rmax:.0f}%</text>')
    svg.append(f'<text x="4" y="{(pad_t+ph):.0f}" fill="#8892a4" font-size="9">{rmin:.0f}%</text>')
    svg.append(f'<text x="{width-pad_r+2:.0f}" y="{(pad_t+ph):.0f}" fill="#8892a4" font-size="9">{amax:.0f}亿</text>')
    svg.append(f'<text x="{pad_l:.0f}" y="{height-3:.0f}" fill="#5a6478" font-size="9">第{pts[0]["周"]}周</text>')
    svg.append(f'<text x="{width-pad_r:.0f}" y="{height-3:.0f}" fill="#5a6478" font-size="9" text-anchor="end">第{pts[-1]["周"]}周</text>')
    svg.append('</svg>')
    return "".join(svg)


_STAGE_STYLE = {
    "启动": ("🟢", "#2ecc71"), "加速": ("🟢", "#2ecc71"),
    "高潮": ("🔴", "#e74c3c"), "放缓": ("🟡", "#f39c12"),
    "衰退": ("⚫", "#95a5a6"), "间断": ("⬜", "#3a4660"),
    "伪启动": ("⚠️", "#5a6478"),
}


def _weekly_detail_html(rows):
    """逐周明细表 HTML(默认折叠)。"""
    H = ['<details class="wk-det"><summary>📋 展开周度明细</summary><table class="wktbl"><thead><tr>',
         '<th>周</th><th>周涨跌幅</th><th>累计涨幅</th><th>成交额(亿)</th>',
         '<th>成交额变化</th><th>周排名</th><th>排名变化</th><th>阶段</th></tr></thead><tbody>']
    prev_amt, prev_rank = None, None
    for r in rows:
        if r["周涨跌幅"] is None:
            H.append(f'<tr class="gap"><td>第{r["周"]}周</td><td colspan="7" style="color:#3a4660;">⬜ 间断(未进活跃池)</td></tr>')
            prev_amt, prev_rank = None, None
            continue
        ret_cls = "pos" if r["周涨跌幅"] >= 0 else "neg"
        cum_cls = "pos" if r["累计涨幅"] >= 0 else "neg"
        amt_ch = "—"
        if prev_amt and prev_amt > 0:
            ch = (r["周成交额"] / prev_amt - 1) * 100
            amt_cls = "pos" if ch >= 0 else "neg"
            amt_ch = f'<span class="{amt_cls}">{ch:+.1f}%</span>'
        rk_ch = "—"
        if prev_rank is not None:
            d = prev_rank - r["周排名"]  # 排名变小=上升
            if d > 0:
                rk_ch = f'<span class="pos">↑{d}</span>'
            elif d < 0:
                rk_ch = f'<span class="neg">↓{-d}</span>'
        icon, col = _STAGE_STYLE.get(r["阶段"], ("", "#888"))
        bear_cls = " bear" if r.get("熊市周") else ""
        stage_txt = f'{icon} {r["阶段"]}'
        if r.get("熊市周"):
            stage_txt += ' 🐻熊市'
        H.append(
            f'<tr class="{bear_cls.strip()}"><td>第{r["周"]}周</td>'
            f'<td class="{ret_cls}">{r["周涨跌幅"]:+.1f}%</td>'
            f'<td class="{cum_cls}">{r["累计涨幅"]:+.1f}%</td>'
            f'<td>{r["周成交额"]:.0f}</td><td>{amt_ch}</td>'
            f'<td>第{r["周排名"]}名</td><td>{rk_ch}</td>'
            f'<td style="color:{col};">{stage_txt}</td></tr>')
        prev_amt, prev_rank = r["周成交额"], r["周排名"]
    H.append('</tbody></table></details>')
    return "".join(H)


def _switch_compare_html(old_ind, old_rows, new_ind, new_rows):
    """切换前后对比:旧主线末4周 + 新主线初4周并排。"""
    old_last4 = [r for r in old_rows if r["周涨跌幅"] is not None][-4:]
    new_first4 = [r for r in new_rows if r["周涨跌幅"] is not None][:4]

    def _col(rows, name):
        H = [f'<div class="cmp-col"><div class="cmp-h">{name}</div><table class="cmptbl">',
             '<thead><tr><th>周</th><th>涨幅</th><th>成交额</th><th>排名</th></tr></thead><tbody>']
        prev_rk = None
        for r in rows:
            ret_cls = "pos" if r["周涨跌幅"] >= 0 else "neg"
            rk_note = ""
            if prev_rk is not None:
                d = prev_rk - r["周排名"]
                rk_note = f' <span class="pos">↑{d}</span>' if d > 0 else (f' <span class="neg">↓{-d}</span>' if d < 0 else "")
            H.append(f'<tr><td>第{r["周"]}周</td><td class="{ret_cls}">{r["周涨跌幅"]:+.1f}%</td>'
                     f'<td>{r["周成交额"]:.0f}</td><td>第{r["周排名"]}名{rk_note}</td></tr>')
            prev_rk = r["周排名"]
        H.append('</tbody></table></div>')
        return "".join(H)

    return (f'<div class="cmp-wrap">{_col(old_last4, f"旧主线·{old_ind} 末4周")}'
            f'{_col(new_first4, f"新主线·{new_ind} 初4周")}</div>')



def generate_chronicle_report(year_start=2016, year_end=2025):
    """生成主线编年史 HTML + CSV。"""
    # ── 加载真实数据 ──
    ml_path = os.path.join(RAW_DIR, f"{year_start}_{year_end}_mainlines_v3.csv")
    sw_path = os.path.join(RAW_DIR, f"{year_start}_{year_end}_switch_signals.csv")
    if not os.path.exists(ml_path):
        print(f"[ERROR] 缺少 {ml_path},请先运行 switch-study 生成 v3 数据。")
        return None
    ml_df = pd.read_csv(ml_path)
    sw_df = pd.read_csv(sw_path) if os.path.exists(sw_path) else pd.DataFrame()

    cat_path = os.path.join(RAW_DIR, "catalyst_events_full.csv")
    cat_df = pd.read_csv(cat_path) if os.path.exists(cat_path) else pd.DataFrame()

    cyc_path = os.path.join(RAW_DIR, "sw31_cycle_phases.csv")
    cyc_df = pd.read_csv(cyc_path) if os.path.exists(cyc_path) else pd.DataFrame()
    cycle_map = {}
    if not cyc_df.empty and "行业名称" in cyc_df.columns:
        for _, r in cyc_df.iterrows():
            cycle_map[str(r["行业名称"])] = r.get("产能周期阶段", "未标注")

    # 仅中期/长期
    ml_df = ml_df[ml_df["级别"].isin(["中期主线", "长期主线"])].copy()
    ml_df["开始日期ts"] = ml_df.get("开始日期").map(_safe_ts)
    ml_df["结束日期ts"] = ml_df.get("结束日期").map(_safe_ts)

    # ── 构建每年叙事 ──
    yearly = {}
    for year in range(year_start, year_end + 1):
        yr_ml = ml_df[ml_df["年份"] == year].sort_values(["开始周", "行业"]).to_dict("records")
        yr_sw = sw_df[sw_df["年份"] == year].sort_values("切换周").to_dict("records") if not sw_df.empty else []

        # 催化剂:落在该年的
        yr_cats = []
        if not cat_df.empty and "日期" in cat_df.columns:
            for _, r in cat_df.iterrows():
                if str(r["日期"]).startswith(str(year)):
                    yr_cats.append({
                        "日期": _safe_ts(r["日期"]),
                        "事件": r.get("事件名称", ""),
                        "关联行业": str(r.get("关联行业", "")),
                        "重要性": r.get("重要性", 0),
                    })

        yearly[year] = {"mainlines": yr_ml, "switches": yr_sw, "catalysts": yr_cats,
                        "weekly": _load_weekly_detail(year)}

    # ── 跨年分析 ──
    cross = _cross_year_analysis(ml_df, sw_df, year_start, year_end)

    # ── 渲染 ──
    html_path = _build_html(yearly, cross, cycle_map, year_start, year_end)
    _save_csv(yearly, year_start, year_end)

    print(f"\n{'=' * 60}")
    print(f"  主线编年史报告完成 ({year_start}-{year_end})")
    print(f"  HTML: {html_path}")
    print(f"{'=' * 60}")
    return html_path


def _match_catalysts(ml, yr_cats, max_n=3):
    """为主线段落匹配催化事件:时间窗口(开始~结束)或关联行业命中。"""
    hits = []
    start_ts = ml.get("开始日期ts")
    end_ts = ml.get("结束日期ts")
    ind = str(ml.get("行业", ""))
    for c in yr_cats:
        cdate = c["日期"]
        cinds = [x.strip() for x in c["关联行业"].split(";") if x.strip()]
        time_hit = (pd.notna(cdate) and pd.notna(start_ts) and pd.notna(end_ts)
                    and start_ts <= cdate <= end_ts)
        ind_hit = ind in cinds
        if time_hit or ind_hit:
            hits.append((c["重要性"] if pd.notna(c["重要性"]) else 0, c["事件"]))
    hits.sort(key=lambda x: -x[0])
    # 去重保序
    seen, out = set(), []
    for _, ev in hits:
        if ev and ev not in seen:
            seen.add(ev)
            out.append(ev)
    return out[:max_n]


def _switch_for_mainline(ml, yr_sw):
    """找到挂在该主线段落之后的接力切换:旧主线=该行业,切换周>=该段结束周,取最早。"""
    ind = str(ml.get("行业", ""))
    end_w = ml.get("结束周", 10 ** 9)
    cands = [s for s in yr_sw
             if str(s.get("旧主线", "")) == ind and s.get("切换周", 10 ** 9) >= end_w]
    if not cands:
        # 退一步:不要求切换周>=结束周,只要旧主线是该行业(同年内该行业的下一段切换)
        cands = [s for s in yr_sw if str(s.get("旧主线", "")) == ind]
    if not cands:
        return None
    cands.sort(key=lambda s: abs(s.get("切换周", 0) - end_w))
    return cands[0]


def _cross_year_analysis(ml_df, sw_df, ystart, yend):
    """行业×年份矩阵 + 反复出现的切换模式。"""
    matrix = defaultdict(dict)
    for _, r in ml_df.iterrows():
        ind = r["行业"]
        y = int(r["年份"])
        rec = matrix[ind].get(y)
        if rec is None:
            matrix[ind][y] = {"level": r["级别"], "max_return": r.get("累计涨幅", 0)}
        else:
            if r.get("累计涨幅", 0) > rec["max_return"]:
                rec["max_return"] = r.get("累计涨幅", 0)
                rec["level"] = r["级别"]
    persistent = {ind: yd for ind, yd in matrix.items() if len(yd) >= 3}

    # 反复切换模式(行业大类),>=3年出现
    pat_by_year = defaultdict(list)
    if not sw_df.empty:
        for _, r in sw_df.iterrows():
            og = _SECTOR_GROUP.get(r.get("旧主线", ""), "其他")
            ng = _SECTOR_GROUP.get(r.get("新主线", ""), "其他")
            pat = f"{og}→{ng}"
            pat_by_year[pat].append({
                "year": int(r["年份"]),
                "old": r.get("旧主线", ""), "new": r.get("新主线", ""),
                "old_ret": r.get("旧_累计涨幅", 0), "new_ret": r.get("新_累计涨幅", 0),
            })
    recurring = {p: d for p, d in pat_by_year.items()
                 if len(set(x["year"] for x in d)) >= 3}
    recurring = dict(sorted(recurring.items(), key=lambda kv: -len(kv[1])))

    return {"matrix": dict(matrix), "persistent": persistent, "recurring": recurring}


def _build_html(yearly, cross, cycle_map, ystart, yend):
    total_ml = sum(len(d["mainlines"]) for d in yearly.values())
    total_sw = sum(len(d["switches"]) for d in yearly.values())

    H = []
    H.append(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{ystart}-{yend} 主线编年史</title>
<style>
:root{{--bg:#0a0e17;--card:#131a2b;--card2:#1a2340;--text:#e8eaf0;--text2:#8892a4;--text3:#5a6478;
--gold:#f1c40f;--blue:#3498db;--green:#2ecc71;--red:#e74c3c;--orange:#f39c12;--border:#1e2a42;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.7;padding:20px;}}
.c{{max-width:1200px;margin:0 auto;}}
.hd{{background:linear-gradient(135deg,#0f1629,#1a2a4a,#0d1b2a);border:1px solid var(--border);border-radius:16px;padding:40px;margin-bottom:24px;text-align:center;}}
.hd h1{{font-size:32px;background:linear-gradient(90deg,var(--gold),var(--orange),var(--red));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;}}
.hd .s{{color:var(--text2);font-size:15px;}}
.ch{{background:var(--card);border:1px solid var(--border);border-radius:14px;margin-bottom:24px;overflow:hidden;}}
.ch-hd{{padding:20px 28px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;transition:background .2s;}}
.ch-hd:hover{{background:var(--card2);}}
.ch-tt{{display:flex;align-items:center;gap:14px;}}.ch-tt h2{{font-size:24px;}}
.era{{padding:3px 12px;border-radius:14px;font-size:13px;font-weight:600;}}
.ch-meta{{color:var(--text2);font-size:13px;display:flex;gap:16px;flex-wrap:wrap;}}
.tg{{color:var(--text3);transition:transform .3s;}}.ch.open .tg{{transform:rotate(180deg);}}
.ch-bd{{padding:0 28px 28px;display:none;}}.ch-bd.show{{display:block;}}
.macro{{background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;padding:14px 18px;margin-bottom:20px;font-size:14px;color:var(--text2);}}
.tl{{position:relative;padding-left:30px;margin-bottom:8px;}}
.tl-ln{{position:absolute;left:14px;top:0;bottom:0;width:2px;background:linear-gradient(180deg,var(--gold),var(--blue),var(--green),var(--red));}}
.nd{{position:relative;margin-bottom:24px;}}
.nd-dot{{position:absolute;left:-24px;top:6px;width:14px;height:14px;border-radius:50%;border:2px solid var(--bg);}}
.ml{{background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;padding:16px 20px;}}
.ml:hover{{border-color:var(--blue);}}
.ml-hd{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}}
.ml-nm{{font-size:17px;font-weight:700;}}
.badge{{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;}}
.ml-st{{display:flex;gap:16px;font-size:13px;color:var(--text2);margin-bottom:8px;flex-wrap:wrap;}}
.ml-st .pos{{color:var(--red);}}.ml-st .neg{{color:var(--green);}}
.cat{{display:inline-block;padding:2px 8px;border-radius:8px;font-size:11px;background:rgba(243,156,18,0.15);color:var(--orange);margin:2px 4px 2px 0;}}
.sw-a{{background:rgba(241,196,15,0.04);border:1px solid rgba(241,196,15,0.15);border-radius:10px;padding:16px 20px;margin:0 0 24px;}}
.sw-t{{font-size:14px;font-weight:700;color:var(--gold);margin-bottom:10px;}}
.sw-g{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;}}
@media(max-width:768px){{.sw-g{{grid-template-columns:1fr;}}}}
.sw-bx{{padding:12px;border-radius:8px;font-size:13px;}}
.sw-bx.top{{background:rgba(231,76,60,0.06);border:1px solid rgba(231,76,60,0.15);}}
.sw-bx.cr{{background:rgba(52,152,219,0.06);border:1px solid rgba(52,152,219,0.15);}}
.sw-bx.fm{{background:rgba(46,204,113,0.06);border:1px solid rgba(46,204,113,0.15);}}
.sw-bx h4{{margin-bottom:6px;font-size:13px;}}.sw-bx h4.t{{color:var(--red);}}.sw-bx h4.c{{color:var(--blue);}}.sw-bx h4.f{{color:var(--green);}}
.sw-d{{color:var(--text2);font-size:12px;line-height:1.7;}}
.scb{{display:inline-block;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;margin-left:4px;}}
.sb-high{{background:rgba(231,76,60,0.2);color:var(--red);}}.sb-med{{background:rgba(243,156,18,0.2);color:var(--orange);}}.sb-low{{background:rgba(149,165,166,0.15);color:var(--text3);}}
.ysum{{background:rgba(52,152,219,0.06);border:1px solid rgba(52,152,219,0.15);border-radius:10px;padding:16px 20px;margin-top:16px;font-size:14px;line-height:1.8;}}
.ysum strong{{color:var(--blue);}}
.cy{{background:var(--card);border:1px solid var(--gold);border-radius:14px;padding:28px;margin-bottom:24px;}}
.cy h2{{color:var(--gold);font-size:22px;margin-bottom:16px;}}
.mtbl{{width:100%;border-collapse:collapse;font-size:12px;margin:16px 0;}}
.mtbl th{{background:rgba(255,255,255,0.05);padding:8px 6px;text-align:center;color:var(--text2);}}
.mtbl td{{padding:6px;text-align:center;border:1px solid rgba(255,255,255,0.05);}}
.mcell{{display:inline-block;padding:2px 6px;border-radius:6px;font-size:11px;font-weight:600;}}
.pc{{background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:12px;}}
.pc h3{{font-size:15px;color:var(--orange);margin-bottom:8px;}}
.pi{{font-size:12px;color:var(--text2);padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.03);}}
.pi:last-child{{border-bottom:none;}}
.ft{{text-align:center;padding:30px;color:var(--text3);font-size:12px;}}
/* 逐周明细表 */
.wk-det{{margin-top:10px;}}
.wk-det summary{{cursor:pointer;font-size:12px;color:var(--blue);padding:4px 0;}}
.wk-det summary:hover{{color:var(--gold);}}
.wktbl{{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px;}}
.wktbl th{{background:rgba(255,255,255,0.05);padding:5px 4px;text-align:center;color:var(--text2);font-weight:600;}}
.wktbl td{{padding:4px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.04);}}
.wktbl tr.gap td{{color:#3a4660;font-style:italic;}}
.wktbl tr.bear td{{background:rgba(231,76,60,0.06);}}
.wktbl .pos{{color:var(--red);}}.wktbl .neg{{color:var(--green);}}
.mini{{margin-top:8px;background:rgba(255,255,255,0.02);border-radius:6px;padding:6px;}}
/* 切换前后对比 */
.cmp-wrap{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px;}}
@media(max-width:768px){{.cmp-wrap{{grid-template-columns:1fr;}}}}
.cmp-col{{background:rgba(255,255,255,0.03);border-radius:8px;padding:8px;}}
.cmp-h{{font-size:12px;font-weight:600;color:var(--text2);margin-bottom:6px;text-align:center;}}
.cmptbl{{width:100%;border-collapse:collapse;font-size:11px;}}
.cmptbl th{{color:var(--text3);font-weight:600;padding:3px;text-align:center;}}
.cmptbl td{{padding:3px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.04);}}
.cmptbl .pos{{color:var(--red);}}.cmptbl .neg{{color:var(--green);}}
</style></head><body><div class="c">
""")

    H.append(f"""
<div class="hd"><h1>📖 {ystart}-{yend} A股主线编年史</h1>
<div class="s">逐年 · 逐段 · 逐次切换 —— 主线如何诞生、演进、衰退、接力</div>
<div class="s" style="margin-top:8px;font-size:13px;color:var(--text3);">
{yend-ystart+1}年 · {total_ml}段中期/长期主线 · {total_sw}次接力切换 · 31行业×产能周期全标注</div></div>
""")

    # ── 逐年章节 ──
    for year in range(ystart, yend + 1):
        era_name, era_color, era_desc = _ERA_LABELS.get(year, ("", "#888888", ""))
        d = yearly.get(year, {"mainlines": [], "switches": [], "catalysts": [], "weekly": pd.DataFrame()})
        ml_list = d["mainlines"]
        yr_sw = d["switches"]
        yr_cats = d["catalysts"]
        yr_weekly = d["weekly"]
        yr_long = sum(1 for m in ml_list if m.get("级别") == "长期主线")
        yr_mid = sum(1 for m in ml_list if m.get("级别") == "中期主线")
        is_first = (year == ystart)
        H.append(f"""
<div class="ch{' open' if is_first else ''}" id="ch{year}">
  <div class="ch-hd" onclick="tog({year})">
    <div class="ch-tt"><h2>{year}</h2>
      <span class="era" style="background:rgba({_hex_rgb(era_color)},0.2);color:{era_color};">{era_name}</span></div>
    <div class="ch-meta"><span>长期{yr_long}</span><span>中期{yr_mid}</span><span>接力{len(yr_sw)}</span></div>
    <span class="tg">▼</span>
  </div>
  <div class="ch-bd{' show' if is_first else ''}">
    <div class="macro">📌 {era_desc}</div>
    <div class="tl"><div class="tl-ln"></div>
""")
        for ml in ml_list:
            ind = ml.get("行业", "")
            level = ml.get("级别", "")
            cum = ml.get("累计涨幅", 0)
            span = ml.get("总跨度周数", 0)
            aw = ml.get("活跃周数", 0)
            ar = ml.get("活跃率", 0)
            avg_rk = ml.get("平均排名", 0)
            sw_ = ml.get("开始周", "")
            ew = ml.get("结束周", "")
            color = _LEVEL_COLORS.get(level, "#888888")
            grp = _SECTOR_GROUP.get(ind, "其他")
            gc = _GROUP_COLORS.get(grp, "#888888")
            cyc = cycle_map.get(ind, "未标注")
            ret_cls = "pos" if cum >= 0 else "neg"
            ret_s = f"+{cum:.1f}%" if cum >= 0 else f"{cum:.1f}%"
            cats = _match_catalysts(ml, yr_cats)

            # 逐周明细(从开始周到结束周全周序列,含间断)
            active_weeks = []
            raw_wl = ml.get("周列表", "[]")
            try:
                active_weeks = [int(x) for x in str(raw_wl).strip("[]").split(",") if x.strip()]
            except (ValueError, AttributeError):
                active_weeks = []
            # 熊市周:从 mainline 的"熊市周"字段解析出周号(CSV 中为 (年,周) 元组字符串)
            bear_weeks = []
            raw_bw = str(ml.get("熊市周", "[]"))
            try:
                bw_clean = raw_bw.strip("[]() ").replace("(", " ").replace(")", " ")
                for tok in bw_clean.split(","):
                    tok = tok.strip()
                    if tok.isdigit():
                        bear_weeks.append(int(tok))
            except (ValueError, AttributeError):
                bear_weeks = []
            ml_rows = _weekly_for_mainline(yr_weekly, ind, int(sw_), int(ew), active_weeks, bear_weeks)

            H.append(f"""<div class="nd"><div class="nd-dot" style="background:{color};"></div>
  <div class="ml"><div class="ml-hd">
    <span class="ml-nm">{ind}</span>
    <span class="badge" style="background:rgba({_hex_rgb(color)},0.2);color:{color};">{level}</span>
    <span class="badge" style="background:rgba({_hex_rgb(gc)},0.15);color:{gc};">{grp}</span>
    <span class="badge" style="background:rgba(255,255,255,0.05);color:var(--text2);">产能:{cyc}</span></div>
    <div class="ml-st"><span class="{ret_cls}">累计 {ret_s}</span><span>跨度{span}周</span>
      <span>活跃{aw}周({ar:.0%})</span><span>均排名{avg_rk:.1f}</span><span>第{sw_}→{ew}周</span></div>""")
            if cats:
                H.append('<div style="margin-top:4px;">')
                for c in cats:
                    H.append(f'<span class="cat">{c}</span>')
                H.append('</div>')
            # 迷你折线图(默认显示)
            if ml_rows:
                H.append(f'<div class="mini">{_mini_svg(ml_rows)}</div>')
                # 逐周明细表(默认折叠)
                H.append(_weekly_detail_html(ml_rows))
            H.append('</div></div>')

            # 该段主线之后的接力切换
            sw = _switch_for_mainline(ml, yr_sw)
            if sw:
                new_ind = sw.get("新主线", "")
                new_lvl = sw.get("新_级别", "")
                top_sc = sw.get("旧_见顶信号强度", 0)
                top_txt = sw.get("旧_见顶信号", "")
                ferm_sc = sw.get("新_发酵信号强度", 0)
                ferm_txt = sw.get("新_发酵信号", "")
                cross_w = sw.get("交叉窗口周数", 0)
                cross_t = sw.get("交叉类型", "")
                og = _SECTOR_GROUP.get(ind, "其他")
                ng = _SECTOR_GROUP.get(new_ind, "其他")
                sw_type = "跨风格切换" if og != ng else "同风格接力"
                top_html = (top_txt.replace(" | ", "<br>") if "无明显" not in str(top_txt)
                            else "该段主线结束前未检测到显著见顶征兆")
                ferm_html = (ferm_txt.replace(" | ", "<br>") if "无明显" not in str(ferm_txt)
                             else f"{new_ind}在成为主线前无显著异动——突发启动型")
                if cross_w and cross_w > 0:
                    cross_desc = f"重叠约{cross_w:.0f}周({cross_t})——旧主线尚未完全退出,新主线已开始走强"
                elif cross_w == 0 and "突然" in str(cross_t):
                    cross_desc = "突然切换(无预兆)——新旧主线几乎同步交接"
                else:
                    cross_desc = f"{cross_t}——交叉窗口{cross_w:.0f}周"
                H.append(f"""<div class="sw-a"><div class="sw-t">🔄 接力切换: {ind} → {new_ind}
  <span style="font-size:12px;color:var(--text2);font-weight:400;">({sw_type}: {og}→{ng})</span></div>
  <div class="sw-g">
    <div class="sw-bx top"><h4 class="t">⚠️ {ind} 见顶信号<span class="scb {_score_cls(top_sc)}">{top_sc}项</span></h4>
      <div class="sw-d">{top_html}</div></div>
    <div class="sw-bx cr"><h4 class="c">🔀 交叉窗口</h4><div class="sw-d">{cross_desc}</div></div>
    <div class="sw-bx fm"><h4 class="f">🌱 {new_ind} 发酵信号<span class="scb {_score_cls(ferm_sc)}">{ferm_sc}项</span></h4>
      <div class="sw-d">{ferm_html}</div></div>
  </div>""")
                # 前后对比周度明细:旧主线末4周 + 新主线初4周
                sw_week = sw.get("切换周", ew)
                try:
                    sw_week_i = int(sw_week)
                except (ValueError, TypeError):
                    sw_week_i = int(ew)
                old_cmp = _weekly_for_mainline(yr_weekly, ind, max(1, sw_week_i - 5), sw_week_i, list(range(max(1, sw_week_i - 5), sw_week_i + 1)))
                new_cmp = _weekly_for_mainline(yr_weekly, new_ind, sw_week_i, sw_week_i + 5, list(range(sw_week_i, sw_week_i + 6)))
                if old_cmp or new_cmp:
                    H.append(_switch_compare_html(ind, old_cmp, new_ind, new_cmp))
                H.append("</div>")

        # 年度小结
        if ml_list:
            inds = list({m.get("行业", "") for m in ml_list})
            grps = list({_SECTOR_GROUP.get(i, "其他") for i in inds})
            best = max(ml_list, key=lambda x: x.get("累计涨幅", -10 ** 9))
            br = best.get("累计涨幅", 0)
            brs = f"+{br:.1f}%" if br >= 0 else f"{br:.1f}%"
            H.append(f"""<div class="ysum"><strong>{year}年小结:</strong>
  全年{len(ml_list)}条中期/长期主线(长期{yr_long}+中期{yr_mid}),涉及{len(inds)}个行业、{len(grps)}大风格({', '.join(grps)})。
  最强主线为<strong>{best.get('行业','')}</strong>({best.get('级别','')},{brs},{best.get('总跨度周数',0)}周)。
  全年{len(yr_sw)}次接力切换。</div>""")
        H.append('</div></div></div>')  # tl, ch-bd, ch

    # ── 跨年分析 ──
    persistent = cross["persistent"]
    recurring = cross["recurring"]
    H.append('<div class="cy"><h2>🔍 跨年纵向分析</h2>')
    if persistent:
        H.append('<h3 style="font-size:16px;margin:16px 0 10px;">📊 跨年活跃行业(≥3年作为中期/长期主线)</h3>')
        H.append('<table class="mtbl"><thead><tr><th>行业</th>')
        for y in range(ystart, yend + 1):
            H.append(f'<th>{y}</th>')
        H.append('<th>年数</th></tr></thead><tbody>')
        for ind in sorted(persistent, key=lambda x: -len(persistent[x])):
            yd = persistent[ind]
            H.append(f'<tr><td style="text-align:left;font-weight:600;">{ind}</td>')
            for y in range(ystart, yend + 1):
                if y in yd:
                    lv = yd[y]["level"]
                    ret = yd[y]["max_return"]
                    col = _LEVEL_COLORS.get(lv, "#888888")
                    rs = f"+{ret:.0f}%" if ret >= 0 else f"{ret:.0f}%"
                    H.append(f'<td><span class="mcell" style="background:rgba({_hex_rgb(col)},0.2);color:{col};">{rs}</span></td>')
                else:
                    H.append('<td>—</td>')
            H.append(f'<td style="font-weight:700;color:var(--gold);">{len(yd)}</td></tr>')
        H.append('</tbody></table>')
    if recurring:
        H.append('<h3 style="font-size:16px;margin:24px 0 10px;">🔄 反复出现的切换模式(≥3年)</h3>')
        for pat, insts in recurring.items():
            yrs = sorted({x["year"] for x in insts})
            H.append(f'<div class="pc"><h3>{pat} — {len(yrs)}年({", ".join(map(str, yrs))})</h3>')
            for it in insts[:12]:
                ors = f"+{it['old_ret']:.1f}%" if it["old_ret"] >= 0 else f"{it['old_ret']:.1f}%"
                nrs = f"+{it['new_ret']:.1f}%" if it["new_ret"] >= 0 else f"{it['new_ret']:.1f}%"
                H.append(f'<div class="pi">{it["year"]}年: {it["old"]}({ors}) → {it["new"]}({nrs})</div>')
            H.append('</div>')
    H.append('</div>')

    H.append(f"""
<div class="ft">主线编年史 · 容间断滑窗算法 v3 · 数据源:申万31一级行业日线 {ystart}-{yend}<br>
{total_ml}段中期/长期主线 · {total_sw}次接力切换</div></div>
<script>function tog(y){{var c=document.getElementById('ch'+y);var b=c.querySelector('.ch-bd');
c.classList.toggle('open');b.classList.toggle('show');}}</script>
</body></html>""")

    out = os.path.join(REPORT_DIR, f"{ystart}_{yend}_mainline_chronicle.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(H))
    print(f"  ✅ 编年史HTML: {out} ({os.path.getsize(out)/1024:.0f}KB)")
    return out


def _save_csv(yearly, ystart, yend):
    rows = []
    for year, d in yearly.items():
        for i, ml in enumerate(d["mainlines"]):
            rows.append({
                "年份": year, "序号": i + 1, "行业": ml.get("行业", ""),
                "级别": ml.get("级别", ""), "开始周": ml.get("开始周", ""),
                "结束周": ml.get("结束周", ""), "跨度周数": ml.get("总跨度周数", 0),
                "累计涨幅": ml.get("累计涨幅", 0), "活跃率": ml.get("活跃率", 0),
                "平均排名": ml.get("平均排名", 0),
            })
    out = os.path.join(RAW_DIR, f"{ystart}_{yend}_chronicle.csv")
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  ✅ 编年史CSV: {out}")


if __name__ == "__main__":
    import sys
    s = int(sys.argv[1]) if len(sys.argv) > 1 else 2016
    e = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    generate_chronicle_report(s, e)
