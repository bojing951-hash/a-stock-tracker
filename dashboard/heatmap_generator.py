#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
heatmap_generator.py
生成46季度×31行业的涨跌幅热力图HTML
以及主线切换时间轴HTML，以及产能周期×主线叠加分析
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime


def _norm_date(v):
    """规范化周期日期: '至今'->今天, '2022-11'->'2022-11-01'"""
    v = str(v).strip()
    if "至今" in v or v in ("nan", ""):
        return "2026-06-22"
    if len(v) == 7:
        return f"{v}-01"
    return v


class HeatmapGenerator:

    def __init__(self, project_root=None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = project_root
        self.overview_df = None
        self.switches_df = None
        self.mainlines_df = None
        self.cycle_df = None
        self.catalysts_df = None

    def load_data(self):
        p = os.path.join(self.project_root, "raw_data", "quarterly_overview.csv")
        if os.path.exists(p):
            self.overview_df = pd.read_csv(p)
            print(f"  ✅ 季度总览: {len(self.overview_df)}行")
        else:
            print(f"  ❌ {p} 不存在，请先运行 python3 main.py overview")
            return False

        p2 = os.path.join(self.project_root, "raw_data", "mainline_switches.csv")
        if os.path.exists(p2):
            self.switches_df = pd.read_csv(p2)
            print(f"  ✅ 主线切换: {len(self.switches_df)}行")

        p3 = os.path.join(self.project_root, "raw_data", "mainline_periods.csv")
        if os.path.exists(p3):
            self.mainlines_df = pd.read_csv(p3)
            print(f"  ✅ 主线段落: {len(self.mainlines_df)}行")

        p4 = os.path.join(self.project_root, "raw_data", "industry_cycle.csv")
        if os.path.exists(p4):
            self.cycle_df = pd.read_csv(p4, encoding="utf-8-sig")
            print(f"  ✅ 产能周期: {len(self.cycle_df)}行")

        p5 = os.path.join(self.project_root, "raw_data", "catalyst_events_full.csv")
        if os.path.exists(p5):
            self.catalysts_df = pd.read_csv(p5, parse_dates=["日期"])
            print(f"  ✅ 催化剂: {len(self.catalysts_df)}条")

        return True

    # ─────────────────────────────────────────────
    # 一、季度热力图
    # ─────────────────────────────────────────────

    def generate_quarterly_heatmap_html(self):
        df = self.overview_df
        if df is None:
            return None

        pivot = df.pivot_table(index="行业名称", columns="季度",
                               values="季度涨跌幅_pct", aggfunc="first")
        quarters = sorted(df["季度"].unique())
        industries = sorted(df["行业名称"].unique())
        row_sums = pivot.sum(axis=1)
        industries_sorted = row_sums.sort_values(ascending=False).index.tolist()

        top3_set, bot3_set = set(), set()
        for q in quarters:
            q_data = df[df["季度"] == q].sort_values("季度涨跌幅_pct", ascending=False)
            if len(q_data) >= 3:
                for _, r in q_data.head(3).iterrows():
                    top3_set.add((r["行业名称"], q))
                for _, r in q_data.tail(3).iterrows():
                    bot3_set.add((r["行业名称"], q))

        quarter_catalysts = {}
        if self.catalysts_df is not None:
            cats = self.catalysts_df.copy()
            cats["季度"] = cats["日期"].dt.to_period("Q").astype(str)
            for q in quarters:
                q_cats = cats[cats["季度"] == q]
                if not q_cats.empty:
                    top_cats = q_cats.nlargest(3, "重要性")
                    quarter_catalysts[q] = "; ".join(top_cats["事件名称"].astype(str).tolist())

        def val_to_color(v):
            if pd.isna(v):
                return "#f0f0f0"
            v = max(-50, min(50, v))
            if v > 0:
                intensity = min(v / 40, 1.0)
                r = int(255 - intensity * 155); g = int(255 - intensity * 55); b = int(255 - intensity * 155)
                return f"rgb({r},{g},{b})"
            elif v < 0:
                intensity = min(abs(v) / 30, 1.0)
                r = int(255 - intensity * 55); g = int(255 - intensity * 155); b = int(255 - intensity * 155)
                return f"rgb({r},{g},{b})"
            return "#ffffff"

        html_parts = ["""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>A股31行业 季度涨跌幅热力图 (2015-2026)</title>
<style>
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 20px; background: #fafafa; }
h1 { text-align: center; color: #333; font-size: 22px; }
h2 { color: #555; font-size: 16px; margin-top: 30px; }
.subtitle { text-align: center; color: #888; font-size: 13px; margin-bottom: 20px; }
.heatmap-container { overflow-x: auto; margin: 20px 0; }
table.heatmap { border-collapse: collapse; font-size: 11px; min-width: 100%; }
table.heatmap th { position: sticky; background: #333; color: #fff; padding: 4px 6px;
    font-weight: normal; white-space: nowrap; writing-mode: vertical-rl; text-orientation: mixed;
    height: 80px; font-size: 10px; top: 0; }
table.heatmap th.row-header { writing-mode: horizontal-tb; text-align: right;
    padding-right: 8px; background: #444; position: sticky; left: 0; z-index: 2; min-width: 70px; top: 0; }
table.heatmap th.corner { position: sticky; left: 0; top: 0; z-index: 3; background: #222; }
table.heatmap td { padding: 3px 5px; text-align: center; white-space: nowrap;
    border: 1px solid rgba(0,0,0,0.08); font-size: 10px; min-width: 42px; cursor: default; }
table.heatmap td.top3 { font-weight: bold; box-shadow: inset 0 0 0 2px #ff6600; }
table.heatmap td.bot3 { font-weight: bold; box-shadow: inset 0 0 0 2px #0066ff; }
table.heatmap tr:hover td { opacity: 0.85; }
.legend { display: flex; align-items: center; gap: 15px; margin: 15px 0; font-size: 12px; flex-wrap: wrap; }
.legend-box { width: 16px; height: 16px; display: inline-block; border: 1px solid #ccc; }
.summary-table { border-collapse: collapse; font-size: 12px; margin: 15px 0; }
.summary-table th, .summary-table td { border: 1px solid #ddd; padding: 5px 8px; vertical-align: top; }
.summary-table th { background: #f5f5f5; }
.pos { color: #c0392b; }
.neg { color: #2980b9; }
</style>
</head>
<body>
<h1>A股31行业 季度涨跌幅热力图</h1>
<p class="subtitle">数据范围: 2015Q1 ~ 最新 | 橙框=季度TOP3 | 蓝框=季度BOTTOM3 | 颜色深浅=涨跌幅度</p>

<div class="legend">
    <span><span class="legend-box" style="background:#64c864"></span> 涨幅>20%</span>
    <span><span class="legend-box" style="background:#b4e8b4"></span> 涨幅5-20%</span>
    <span><span class="legend-box" style="background:#ffffff; border:1px solid #ccc"></span> 0%</span>
    <span><span class="legend-box" style="background:#b4b4e8"></span> 跌幅5-20%</span>
    <span><span class="legend-box" style="background:#6464c8"></span> 跌幅>20%</span>
    <span>| <span class="legend-box" style="box-shadow: inset 0 0 0 2px #ff6600; background:#fff"></span> TOP3</span>
    <span><span class="legend-box" style="box-shadow: inset 0 0 0 2px #0066ff; background:#fff"></span> BOTTOM3</span>
</div>

<div class="heatmap-container">
<table class="heatmap">
<thead><tr><th class="corner">行业＼季度</th>
"""]

        for q in quarters:
            html_parts.append(f'<th>{q}</th>')
        html_parts.append('</tr></thead><tbody>')

        for ind in industries_sorted:
            html_parts.append(f'<tr><th class="row-header">{ind}</th>')
            for q in quarters:
                val = pivot.loc[ind, q] if ind in pivot.index and q in pivot.columns else None
                color = val_to_color(val if pd.notna(val) else None)
                css_class = ""
                if (ind, q) in top3_set:
                    css_class = " top3"
                elif (ind, q) in bot3_set:
                    css_class = " bot3"
                display = f"{val:+.1f}" if pd.notna(val) else "-"
                val_class = "pos" if pd.notna(val) and val > 0 else ("neg" if pd.notna(val) and val < 0 else "")
                tooltip = f"{ind} {q}: {display}%"
                cat_tip = quarter_catalysts.get(q, "")
                if cat_tip:
                    tooltip += f" | 催化剂: {cat_tip[:60]}"
                html_parts.append(
                    f'<td class="{val_class}{css_class}" style="background:{color}" '
                    f'title="{tooltip}">{display}</td>')
            html_parts.append('</tr>')
        html_parts.append('</tbody></table></div>')

        # 年度主线摘要
        html_parts.append('<h2>年度主线摘要</h2>')
        html_parts.append('<table class="summary-table"><thead><tr>'
                          '<th>年份</th><th>Q1 TOP3</th><th>Q2 TOP3</th>'
                          '<th>Q3 TOP3</th><th>Q4 TOP3</th>'
                          '<th>全年催化剂</th></tr></thead><tbody>')
        years = sorted(set(q[:4] for q in quarters))
        for year in years:
            html_parts.append(f'<tr><td><b>{year}</b></td>')
            for qn in range(1, 5):
                q_label = f"{year}Q{qn}"
                q_data = df[df["季度"] == q_label].sort_values("季度涨跌幅_pct", ascending=False)
                if q_data.empty:
                    html_parts.append('<td>-</td>')
                else:
                    items = []
                    for _, r in q_data.head(3).iterrows():
                        v = r["季度涨跌幅_pct"]
                        cls = "pos" if v > 0 else "neg"
                        items.append(f'<span class="{cls}">{r["行业名称"]}{v:+.1f}%</span>')
                    html_parts.append(f'<td>{"<br>".join(items)}</td>')
            year_cats = [quarter_catalysts.get(f"{year}Q{qn}", "") for qn in range(1, 5) if quarter_catalysts.get(f"{year}Q{qn}")]
            html_parts.append(f'<td style="font-size:10px">{"; ".join(year_cats)[:120]}</td>')
            html_parts.append('</tr>')
        html_parts.append('</tbody></table>')

        html_parts.append(f'<p style="color:#aaa;font-size:11px;margin-top:30px">'
                          f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")} | '
                          f'数据: quarterly_overview.csv ({len(df)}行) | '
                          f'催化剂: {len(self.catalysts_df) if self.catalysts_df is not None else 0}条'
                          f'</p></body></html>')

        html = "\n".join(html_parts)
        out_dir = os.path.join(self.project_root, "dashboard", "replay_reports")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "quarterly_heatmap.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ 季度热力图: {out_path} ({len(html) // 1024}KB)")
        return out_path

    # ─────────────────────────────────────────────
    # 二、主线切换全景快照
    # ─────────────────────────────────────────────

    def _get_cycle_phase(self, industry, quarter_str):
        """查找行业在某季度的产能周期阶段(日期规范化)"""
        if self.cycle_df is None:
            return ""
        year = int(quarter_str[:4])
        qn = int(quarter_str[5:].replace("Q", ""))
        mid_date = f"{year}-{(qn-1)*3+2:02d}-15"
        for _, row in self.cycle_df.iterrows():
            ind = str(row.get("行业名称", row.get("行业", "")))
            if ind != industry:
                continue
            s = _norm_date(row.get("起始日期", row.get("起始时间", "")))
            e = _norm_date(row.get("结束日期", row.get("结束时间", "")))
            if s and s <= mid_date:
                if not e or e >= mid_date:
                    return str(row.get("周期阶段_标准化", row.get("周期阶段", "")))
        return ""

    def generate_switch_snapshots(self):
        if self.overview_df is None:
            return None, "无季度总览数据"
        df = self.overview_df
        quarters = sorted(df["季度"].unique())
        quarter_top3 = {}
        for q in quarters:
            q_data = df[df["季度"] == q].sort_values("季度涨跌幅_pct", ascending=False)
            quarter_top3[q] = q_data.head(3)["行业名称"].tolist()
        quarter_median, quarter_mean = {}, {}
        for q in quarters:
            q_data = df[df["季度"] == q]
            quarter_median[q] = q_data["季度涨跌幅_pct"].median()
            quarter_mean[q] = q_data["季度涨跌幅_pct"].mean()

        quarter_catalysts = {}
        if self.catalysts_df is not None:
            cats = self.catalysts_df.copy()
            cats["季度"] = cats["日期"].dt.to_period("Q").astype(str)
            for q in quarters:
                q_cats = cats[cats["季度"] == q]
                if not q_cats.empty:
                    quarter_catalysts[q] = q_cats.nlargest(5, "重要性")[
                        ["事件名称", "事件类型", "关联行业", "影响方向", "重要性"]].to_dict("records")

        snapshots = []
        for i in range(1, len(quarters)):
            prev_q = quarters[i - 1]; curr_q = quarters[i]
            prev_top3 = set(quarter_top3.get(prev_q, []))
            curr_top3 = set(quarter_top3.get(curr_q, []))
            exited = prev_top3 - curr_top3
            entered = curr_top3 - prev_top3
            stayed = prev_top3 & curr_top3
            if not entered and not exited:
                continue
            old_mainline_new_q = []
            for ind in exited:
                new_q_data = df[(df["季度"] == curr_q) & (df["行业名称"] == ind)]
                if not new_q_data.empty:
                    old_mainline_new_q.append({"行业": ind, "退出后涨跌": new_q_data.iloc[0]["季度涨跌幅_pct"]})
            new_mainline_prev_q = []
            for ind in entered:
                prev_q_data = df[(df["季度"] == prev_q) & (df["行业名称"] == ind)]
                if not prev_q_data.empty:
                    new_mainline_prev_q.append({"行业": ind,
                                                "发酵期涨跌": prev_q_data.iloc[0]["季度涨跌幅_pct"],
                                                "上季排名": prev_q_data.iloc[0].get("季度排名", 0)})
            curr_q_all = df[df["季度"] == curr_q].sort_values("季度涨跌幅_pct", ascending=False)
            other_industries = [{"行业": r["行业名称"], "涨跌幅": r["季度涨跌幅_pct"],
                                 "排名": r.get("季度排名", 0)} for _, r in curr_q_all.iterrows()]
            cycle_phases = {}
            for ind in list(entered) + list(exited):
                ph = self._get_cycle_phase(ind, curr_q)
                if ph:
                    cycle_phases[ind] = ph
            median_ret = quarter_median.get(curr_q, 0)
            prev_median = quarter_median.get(prev_q, 0)
            if median_ret > 5 and prev_median > 0:
                market_state = "牛市上涨"
            elif median_ret > 5 and prev_median <= 0:
                market_state = "底部反弹"
            elif median_ret > 0:
                market_state = "温和上涨"
            elif median_ret > -5:
                market_state = "震荡偏弱"
            elif prev_median > 0:
                market_state = "见顶回落"
            else:
                market_state = "熊市下跌"
            snapshots.append({"季度": curr_q, "上季度": prev_q, "大盘状态": market_state,
                              "大盘中位数涨跌": round(median_ret, 2), "上季大盘中位数": round(prev_median, 2),
                              "退出主线": list(exited), "新进主线": list(entered), "延续主线": list(stayed),
                              "旧主线退出后表现": old_mainline_new_q,
                              "新主线发酵期表现": new_mainline_prev_q,
                              "全行业排名": other_industries,
                              "催化剂": quarter_catalysts.get(curr_q, []),
                              "产能周期": cycle_phases})

        html = self._render_switch_snapshots_html(snapshots)
        out_dir = os.path.join(self.project_root, "dashboard", "replay_reports")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "switch_snapshots.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        json_path = os.path.join(self.project_root, "raw_data", "switch_snapshots.json")
        serializable = []
        for s in snapshots:
            ss = {}
            for k, v in s.items():
                ss[k] = list(v) if isinstance(v, set) else v
            serializable.append(ss)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)
        summary = (f"主线切换全景快照: {len(snapshots)}次季度级切换\n"
                   f"HTML报告: {out_path}\nJSON数据: {json_path}")
        return snapshots, summary

    def _render_switch_snapshots_html(self, snapshots):
        parts = ["""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>A股主线切换全景快照 (2015-2026)</title>
<style>
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #fafafa; }
h1 { text-align: center; color: #333; }
.subtitle { text-align: center; color: #888; font-size: 13px; margin-bottom: 30px; }
.snapshot { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 15px 0; background: #fff; }
.snapshot:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.snapshot-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.quarter-label { font-size: 20px; font-weight: bold; color: #333; }
.market-state { padding: 3px 10px; border-radius: 12px; font-size: 12px; color: #fff; }
.state-bull { background: #e74c3c; } .state-bounce { background: #e67e22; }
.state-mild-up { background: #f39c12; } .state-weak { background: #95a5a6; }
.state-top { background: #3498db; } .state-bear { background: #2c3e50; }
.switch-flow { display: flex; align-items: center; gap: 10px; margin: 10px 0; flex-wrap: wrap; }
.industry-tag { padding: 4px 10px; border-radius: 4px; font-size: 12px; display: inline-block; margin: 2px; }
.tag-exit { background: #fadbd8; color: #c0392b; border: 1px solid #e6b0aa; }
.tag-enter { background: #d5f5e3; color: #27ae60; border: 1px solid #a9dfbf; }
.tag-stay { background: #ebf5fb; color: #2980b9; border: 1px solid #aed6f1; }
.tag-cycle { background: #f5eef8; color: #8e44ad; font-size: 10px; margin-left: 3px; }
.arrow { font-size: 20px; color: #999; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }
.detail-box { background: #f9f9f9; border-radius: 6px; padding: 10px; }
.detail-box h4 { margin: 0 0 6px 0; font-size: 13px; color: #555; }
.detail-item { font-size: 12px; margin: 3px 0; color: #666; }
.pos { color: #c0392b; } .neg { color: #2980b9; }
.catalyst-item { background: #fffde7; border-left: 3px solid #ffc107; padding: 4px 8px; margin: 3px 0; font-size: 11px; }
.toc { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
.toc a { color: #2980b9; text-decoration: none; font-size: 12px; margin-right: 10px; }
.rank-bar { display: flex; gap: 2px; margin-top: 5px; flex-wrap: wrap; }
.rank-cell { width: 28px; height: 18px; font-size: 9px; text-align: center; line-height: 18px; border-radius: 2px; color: #fff; }
</style>
</head>
<body>
<h1>A股主线切换全景快照</h1>
<p class="subtitle">每次季度主线变更的完整记录：谁退出、谁接棒、大盘什么状态、其他行业什么反应</p>
"""]
        parts.append('<div class="toc"><b>快速导航: </b>')
        for s in snapshots:
            q = s["季度"]
            entered_str = "+".join(s["新进主线"][:2]) if s["新进主线"] else "延续"
            parts.append(f'<a href="#{q}">{q}({entered_str})</a> ')
        parts.append('</div>')
        for s in snapshots:
            q = s["季度"]; state = s["大盘状态"]
            state_class = {"牛市上涨": "state-bull", "底部反弹": "state-bounce",
                           "温和上涨": "state-mild-up", "震荡偏弱": "state-weak",
                           "见顶回落": "state-top", "熊市下跌": "state-bear"}.get(state, "state-weak")
            parts.append(f'<div class="snapshot" id="{q}">')
            parts.append('<div class="snapshot-header">')
            parts.append(f'<span class="quarter-label">{q}</span>')
            median_v = s["大盘中位数涨跌"]
            median_cls = "pos" if median_v > 0 else "neg"
            parts.append(f'<span><span class="market-state {state_class}">{state}</span> '
                         f'<span class="{median_cls}" style="font-size:13px"> 全行业中位数 {median_v:+.1f}%</span></span>')
            parts.append('</div><div class="switch-flow">')
            for ind in s["退出主线"]:
                ct = f'<span class="tag-cycle">{s["产能周期"][ind]}</span>' if ind in s.get("产能周期", {}) else ""
                parts.append(f'<span class="industry-tag tag-exit">▼ {ind}{ct}</span>')
            if s["退出主线"] and s["新进主线"]:
                parts.append('<span class="arrow">→</span>')
            for ind in s["新进主线"]:
                ct = f'<span class="tag-cycle">{s["产能周期"][ind]}</span>' if ind in s.get("产能周期", {}) else ""
                parts.append(f'<span class="industry-tag tag-enter">▲ {ind}{ct}</span>')
            for ind in s["延续主线"]:
                parts.append(f'<span class="industry-tag tag-stay">● {ind}</span>')
            parts.append('</div><div class="detail-grid">')
            parts.append('<div class="detail-box"><h4>旧主线退出后（本季表现）</h4>')
            for item in s.get("旧主线退出后表现", []):
                v = item["退出后涨跌"]; cls = "pos" if v > 0 else "neg"
                parts.append(f'<div class="detail-item">{item["行业"]}: <span class="{cls}">{v:+.1f}%</span></div>')
            if not s.get("旧主线退出后表现"):
                parts.append('<div class="detail-item">-</div>')
            parts.append('</div><div class="detail-box"><h4>新主线发酵期（上季表现）</h4>')
            for item in s.get("新主线发酵期表现", []):
                v = item["发酵期涨跌"]; cls = "pos" if v > 0 else "neg"
                rank = item.get("上季排名", "")
                rank_str = f" (排名第{int(rank)})" if rank else ""
                parts.append(f'<div class="detail-item">{item["行业"]}: <span class="{cls}">{v:+.1f}%</span>{rank_str}</div>')
            if not s.get("新主线发酵期表现"):
                parts.append('<div class="detail-item">-</div>')
            parts.append('</div></div>')
            if s.get("催化剂"):
                parts.append('<div>')
                for cat in s["催化剂"][:5]:
                    direction = cat.get("影响方向", ""); importance = cat.get("重要性", "")
                    parts.append(f'<div class="catalyst-item">{"⬆" if direction == "正面" else "⬇"} '
                                 f'{cat.get("事件名称", "")} '
                                 f'<span style="color:#999">({cat.get("事件类型", "")} 重要性{importance})</span></div>')
                parts.append('</div>')
            parts.append('<div style="margin-top:8px"><span style="font-size:11px;color:#999">全行业涨跌幅: </span><div class="rank-bar">')
            for item in s.get("全行业排名", [])[:31]:
                v = item["涨跌幅"]
                bg = "#c0392b" if v > 10 else ("#e74c3c" if v > 0 else ("#3498db" if v > -10 else "#2c3e50"))
                parts.append(f'<div class="rank-cell" style="background:{bg}" title="{item["行业"]} {v:+.1f}%">{item["行业"][:2]}</div>')
            parts.append('</div></div></div>')
        parts.append(f'<p style="color:#aaa;font-size:11px;margin-top:30px">'
                     f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")} | '
                     f'切换快照数: {len(snapshots)}</p></body></html>')
        return "\n".join(parts)

    # ─────────────────────────────────────────────
    # 三、产能周期×主线 叠加分析
    # ─────────────────────────────────────────────

    def generate_cycle_mainline_analysis(self):
        if self.overview_df is None or self.cycle_df is None:
            return None, "缺少季度总览或产能周期数据"
        df = self.overview_df
        quarters = sorted(df["季度"].unique())

        def lookup_phase(industry, quarter_str):
            return self._get_cycle_phase(industry, quarter_str)

        phase_data = []
        for q in quarters:
            for _, r in df[df["季度"] == q].iterrows():
                ind = r["行业名称"]
                phase = lookup_phase(ind, q)
                is_top3 = r.get("季度排名", 99) <= 3
                phase_data.append({"季度": q, "行业名称": ind,
                                   "季度涨跌幅_pct": r["季度涨跌幅_pct"],
                                   "季度排名": r.get("季度排名", 99),
                                   "产能周期阶段": phase, "是否主线": is_top3})
        phase_df = pd.DataFrame(phase_data)

        phase_stats = []
        for phase in ["成长期", "复苏期", "景气顶部", "成熟稳定期", "过剩期", "出清期"]:
            p_data = phase_df[phase_df["产能周期阶段"] == phase]
            if p_data.empty:
                continue
            total = len(p_data)
            mc = int(p_data["是否主线"].sum())
            phase_stats.append({"产能周期阶段": phase, "总观测数": total,
                                "成为主线次数": mc,
                                "成为主线概率_pct": round(mc / total * 100, 1),
                                "平均季度涨跌幅_pct": round(p_data["季度涨跌幅_pct"].mean(), 2),
                                "平均季度排名": round(p_data["季度排名"].mean(), 1)})
        stats_df = pd.DataFrame(phase_stats)

        switch_cycle = []
        if self.switches_df is not None:
            for _, sw in self.switches_df.iterrows():
                sd = str(sw.get("切换日期", ""))
                if len(sd) >= 7:
                    year = sd[:4]; month = int(sd[5:7]); qn = (month - 1) // 3 + 1
                    q_label = f"{year}Q{qn}"
                else:
                    continue
                new_main = str(sw.get("新主线", "")); old_main = str(sw.get("旧主线", ""))
                switch_cycle.append({"切换日期": sd, "旧主线": old_main,
                                     "旧主线周期阶段": lookup_phase(old_main, q_label),
                                     "新主线": new_main,
                                     "新主线周期阶段": lookup_phase(new_main, q_label)})
        switch_cycle_df = pd.DataFrame(switch_cycle) if switch_cycle else pd.DataFrame()

        new_main_phase_dist = {}
        if not switch_cycle_df.empty:
            for phase in switch_cycle_df["新主线周期阶段"].dropna().unique():
                if phase:
                    new_main_phase_dist[phase] = int((switch_cycle_df["新主线周期阶段"] == phase).sum())

        summary_lines = ["=" * 60, "  产能周期 × 主线分析", "=" * 60, "",
                         "── 各阶段成为季度TOP3主线的概率 ──"]
        for _, r in stats_df.iterrows():
            summary_lines.append(f"  {r['产能周期阶段']:6s} | 观测{r['总观测数']:3d}次 | "
                                 f"主线{r['成为主线次数']:2d}次({r['成为主线概率_pct']:5.1f}%) | "
                                 f"平均涨跌{r['平均季度涨跌幅_pct']:+6.2f}% | 平均排名{r['平均季度排名']:4.1f}")
        if new_main_phase_dist:
            summary_lines += ["", "── 新主线接棒时处于什么产能周期阶段 ──"]
            total_sw = sum(new_main_phase_dist.values())
            for phase, count in sorted(new_main_phase_dist.items(), key=lambda x: -x[1]):
                pct = count / total_sw * 100
                bar = "█" * int(pct / 2)
                summary_lines.append(f"  {phase:6s} | {count:3d}次 ({pct:4.1f}%) {bar}")
        summary_lines += ["", "── 关键发现 ──"]
        if not stats_df.empty:
            best = stats_df.loc[stats_df["成为主线概率_pct"].idxmax()]
            worst = stats_df.loc[stats_df["成为主线概率_pct"].idxmin()]
            summary_lines.append(f"  ✦ 最容易成为主线的阶段: {best['产能周期阶段']} ({best['成为主线概率_pct']:.1f}%)")
            summary_lines.append(f"  ✦ 最难成为主线的阶段: {worst['产能周期阶段']} ({worst['成为主线概率_pct']:.1f}%)")
        if new_main_phase_dist:
            top_phase = max(new_main_phase_dist, key=new_main_phase_dist.get)
            summary_lines.append(f"  ✦ 新主线最常见周期阶段: {top_phase} ({new_main_phase_dist[top_phase]}次)")
        summary_text = "\n".join(summary_lines)

        stats_path = os.path.join(self.project_root, "raw_data", "cycle_mainline_stats.csv")
        stats_df.to_csv(stats_path, index=False, encoding="utf-8-sig")
        phase_detail_path = os.path.join(self.project_root, "raw_data", "quarterly_with_cycle_phase.csv")
        phase_df.to_csv(phase_detail_path, index=False, encoding="utf-8-sig")
        if not switch_cycle_df.empty:
            sw_cycle_path = os.path.join(self.project_root, "raw_data", "switch_cycle_phases.csv")
            switch_cycle_df.to_csv(sw_cycle_path, index=False, encoding="utf-8-sig")
        print(summary_text)
        print(f"\n✅ 产能周期统计: {stats_path}")
        print(f"✅ 季度明细+周期: {phase_detail_path}")
        return {"phase_stats": stats_df, "phase_detail": phase_df,
                "switch_cycles": switch_cycle_df,
                "new_main_phase_dist": new_main_phase_dist}, summary_text


def main():
    print("=" * 60)
    print("  热力图 + 切换快照 + 产能周期叠加 生成器")
    print("=" * 60)
    gen = HeatmapGenerator()
    if not gen.load_data():
        return
    print("\n[1/3] 生成季度热力图...")
    gen.generate_quarterly_heatmap_html()
    print("\n[2/3] 生成主线切换全景快照...")
    snapshots, summary = gen.generate_switch_snapshots()
    print(summary)
    print("\n[3/3] 生成产能周期×主线分析...")
    gen.generate_cycle_mainline_analysis()
    print("\n" + "=" * 60)
    print("  全部完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
