#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段2 可视化：生成6张图表PNG + backtest_charts.html
依赖: backtest_results/_reports.pkl, cycle_timing_summary.csv,
      phase_effectiveness.csv, deviation_analysis.csv
"""
import os
import base64
import pickle
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 中文字体
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "backtest", "backtest_results")
MODES = ["binary", "aggressive", "conservative"]


def load_data():
    summary = pd.read_csv(os.path.join(OUT_DIR, "cycle_timing_summary.csv"))
    pe = pd.read_csv(os.path.join(OUT_DIR, "phase_effectiveness.csv"))
    dev = pd.read_csv(os.path.join(OUT_DIR, "deviation_analysis.csv"))
    with open(os.path.join(OUT_DIR, "_reports.pkl"), "rb") as f:
        reports = pickle.load(f)
    return summary, pe, dev, reports


def chart1_excess_return(summary):
    """图1: 22行业 binary 超额年化柱状图（排序，A/B组透明度区分）"""
    d = summary.sort_values("binary_超额年化").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(12, 7))
    colors = []
    alphas = []
    for _, r in d.iterrows():
        pos = r["binary_超额年化"] >= 0
        colors.append("tab:green" if pos else "tab:red")
        alphas.append(0.95 if r["数据组别"] == "A" else 0.55)
    bars = ax.barh(d["行业名称"], d["binary_超额年化"], color=colors)
    for b, a in zip(bars, alphas):
        b.set_alpha(a)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("超额年化收益率 % (binary模式: 策略 - 基准)")
    ax.set_title("图1: 22行业产能周期择时超额收益\n(深色=A组2015起, 浅色=B组2021起; 绿=正 红=负)")
    for i, v in enumerate(d["binary_超额年化"]):
        ax.text(v + (0.15 if v >= 0 else -0.15), i, f"{v:+.1f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=8)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    p = os.path.join(OUT_DIR, "chart_1_excess_return.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def chart2_phase_effectiveness(pe):
    """图2: 6周期阶段平均基准年化柱状图"""
    order = ["成长期", "复苏期", "成熟稳定期", "景气顶部", "过剩期", "出清期"]
    pe = pe.set_index("phase").reindex(order).reset_index()
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = ["tab:green", "tab:green", "gray", "orange", "tab:red", "tab:red"]
    bars = ax.bar(pe["phase"], pe["平均基准年化%"], color=colors, alpha=0.85)
    ax.axhline(0, color="black", lw=0.8)
    for b, v, n in zip(bars, pe["平均基准年化%"], pe["样本段数"]):
        ax.text(b.get_x() + b.get_width()/2, v + (1.5 if v >= 0 else -2.5),
                f"{v:+.1f}%\n(n={n})", ha="center", fontsize=9)
    ax.set_ylabel("平均基准年化收益率 %")
    ax.set_title("图2: 周期阶段效果验证（基准满仓年化收益）\n假说: 成长/复苏>0, 过剩/出清<0")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    p = os.path.join(OUT_DIR, "chart_2_phase_effectiveness.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def _plot_nav(ax, lab, title):
    """在 ax 上画策略vs基准净值，并用底色标注买卖区间"""
    d = lab.sort_values("date").reset_index(drop=True)
    ax.plot(d["date"], d["strategy_nav"], label="策略净值", color="tab:red", lw=1.6)
    ax.plot(d["date"], d["benchmark_nav"], label="基准净值", color="tab:blue",
            lw=1.4, alpha=0.8)
    # 标注仓位区间（满仓绿/空仓红阴影）
    if "position" in d.columns:
        pos = d["position"].values
        x = range(len(d))
        # 满仓段
        full = pos >= 0.999
        empty = pos <= 0.001
        import itertools
        for state, color, lab2 in [(full, "#2ca02c", "满仓"), (empty, "#d62728", "空仓")]:
            idxs = np.where(state)[0]
            if len(idxs) == 0:
                continue
            # 连续段
            breaks = np.where(np.diff(idxs) > 1)[0]
            starts = np.concatenate([[idxs[0]], idxs[breaks + 1]])
            ends = np.concatenate([idxs[breaks], [idxs[-1]]])
            for s, e in zip(starts, ends):
                ax.axvspan(d["date"].iloc[s], d["date"].iloc[e],
                           color=color, alpha=0.07)
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)


def chart3_top3_A(reports, summary):
    """图3: A组超额最高3行业净值曲线"""
    a = summary[summary["数据组别"] == "A"].nlargest(3, "binary_超额年化")
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=False)
    for ax, (_, r) in zip(axes, a.iterrows()):
        ind = r["行业名称"]
        lab = reports[ind]["binary"]["labeled"]
        _plot_nav(ax, lab, f"{ind} (A组, 超额{r['binary_超额年化']:+.1f}%)")
    fig.suptitle("图3: A组超额收益TOP3 — 策略 vs 基准净值", fontsize=13, y=1.0)
    plt.tight_layout()
    p = os.path.join(OUT_DIR, "chart_3_top3_A.png")
    plt.savefig(p, dpi=110, bbox_inches="tight"); plt.close()
    return p


def chart4_top2_B(reports, summary):
    """图4: B组超额最高2行业"""
    b = summary[summary["数据组别"] == "B"].nlargest(2, "binary_超额年化")
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.5), sharex=False)
    for ax, (_, r) in zip(axes, b.iterrows()):
        ind = r["行业名称"]
        lab = reports[ind]["binary"]["labeled"]
        _plot_nav(ax, lab, f"{ind} (B组, 超额{r['binary_超额年化']:+.1f}%)")
    fig.suptitle("图4: B组超额收益TOP2 — 策略 vs 基准净值", fontsize=13, y=1.0)
    plt.tight_layout()
    p = os.path.join(OUT_DIR, "chart_4_top2_B.png")
    plt.savefig(p, dpi=110, bbox_inches="tight"); plt.close()
    return p


def chart5_worst2(reports, summary):
    """图5: 超额最差2行业（失败分析）"""
    w = summary.nsmallest(2, "binary_超额年化")
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.5), sharex=False)
    for ax, (_, r) in zip(axes, w.iterrows()):
        ind = r["行业名称"]
        lab = reports[ind]["binary"]["labeled"]
        _plot_nav(ax, lab, f"{ind} (超额{r['binary_超额年化']:+.1f}%, 择时跑输满仓)")
    fig.suptitle("图5: 超额收益最差TOP2 — 失败案例", fontsize=13, y=1.0)
    plt.tight_layout()
    p = os.path.join(OUT_DIR, "chart_5_worst2.png")
    plt.savefig(p, dpi=110, bbox_inches="tight"); plt.close()
    return p


def chart6_deviation(reports):
    """图6: deviation_type=逻辑切换 时段策略vs基准。逻辑切换平均基准收益最高(75%)，验证它是否是策略敌人"""
    # 从所有binary labeled里筛出 deviation_type=='逻辑切换' 的日期段
    segs = []
    for ind, r in reports.items():
        lab = r["binary"]["labeled"]
        if "deviation_type" not in lab.columns:
            continue
        mask = lab["deviation_type"].astype(str).str.contains("逻辑切换")
        sub = lab[mask]
        if len(sub):
            sub = sub.copy(); sub["industry"] = ind
            segs.append(sub)
    if not segs:
        return None
    alls = pd.concat(segs).reset_index(drop=True)
    # 按行业-连续段画
    fig, ax = plt.subplots(figsize=(12, 6))
    # 简化：把每段(行业内逻辑切换连续区间)的 策略vs基准 净值归一化后叠画
    plotted = 0
    for ind, g in alls.groupby("industry"):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < 5:
            continue
        sn = g["strategy_nav"] / g["strategy_nav"].iloc[0]
        bn = g["benchmark_nav"] / g["benchmark_nav"].iloc[0]
        ax.plot(range(len(g)), sn, color="tab:red", alpha=0.5, lw=1)
        ax.plot(range(len(g)), bn, color="tab:blue", alpha=0.5, lw=1)
        plotted += 1
    ax.axhline(1.0, color="black", lw=0.7, ls="--")
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([0],[0],color='tab:red',label='策略净值(归一)'),
                       Line2D([0],[0],color='tab:blue',label='基准净值(归一)')], fontsize=9)
    ax.set_xlabel("逻辑切换时段内交易日序号")
    ax.set_ylabel("归一化净值")
    ax.set_title(f"图6: deviation_type=逻辑切换 时段 — 策略 vs 基准 (共{plotted}个行业段)\n"
                 "逻辑切换段基准平均+75.7%: 说明阶段被'强行切换',策略常踏空")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    p = os.path.join(OUT_DIR, "chart_6_deviation.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def build_html(paths, summary, pe, dev):
    """生成 backtest_charts.html，内嵌PNG"""
    def b64(p):
        with open(p, "rb") as f:
            return base64.b64encode(f.read()).decode()

    cap = {
        "chart_1_excess_return.png": "图1 22行业超额收益(binary模式)",
        "chart_2_phase_effectiveness.png": "图2 周期阶段效果验证",
        "chart_3_top3_A.png": "图3 A组超额TOP3净值",
        "chart_4_top2_B.png": "图4 B组超额TOP2净值",
        "chart_5_worst2.png": "图5 超额最差TOP2(失败案例)",
        "chart_6_deviation.png": "图6 逻辑切换时段分析",
    }
    html = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
            "<style>body{font-family:sans-serif;max-width:1100px;margin:auto;padding:20px}"
            "h2{border-bottom:2px solid #333}img{width:100%;border:1px solid #ddd;margin:8px 0}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px;font-size:13px}"
            ".pos{color:green}.neg{color:red}</style></head><body>"]
    html.append("<h1>产能周期择时策略 — 回测图表</h1>")
    html.append(f"<p>回测行业: {len(summary)} (A组{(summary['数据组别']=='A').sum()} / "
                f"B组{(summary['数据组别']=='B').sum()})</p>")

    # 超额排名表
    html.append("<h2>超额年化收益排名 (binary)</h2><table><tr><th>行业</th><th>组</th>"
                "<th>策略年化</th><th>基准年化</th><th>超额</th><th>夏普</th><th>最大回撤</th></tr>")
    for _, r in summary.sort_values("binary_超额年化", ascending=False).iterrows():
        cls = "pos" if r["binary_超额年化"] >= 0 else "neg"
        html.append(f"<tr><td>{r['行业名称']}</td><td>{r['数据组别']}</td>"
                    f"<td>{r['binary_年化收益']:.2f}%</td><td>{r['binary_基准年化']:.2f}%</td>"
                    f"<td class='{cls}'>{r['binary_超额年化']:+.2f}%</td>"
                    f"<td>{r['binary_夏普']:.2f}</td><td>{r['binary_最大回撤']:.1f}%</td></tr>")
    html.append("</table>")

    for fname in ["chart_1_excess_return.png", "chart_2_phase_effectiveness.png",
                  "chart_3_top3_A.png", "chart_4_top2_B.png",
                  "chart_5_worst2.png", "chart_6_deviation.png"]:
        p = os.path.join(OUT_DIR, fname)
        if os.path.exists(p):
            html.append(f"<h2>{cap[fname]}</h2><img src='data:image/png;base64,{b64(p)}'>")
    html.append("</body></html>")
    out = os.path.join(OUT_DIR, "backtest_charts.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    return out


def main():
    summary, pe, dev, reports = load_data()
    print("生成图表...")
    p1 = chart1_excess_return(summary)
    p2 = chart2_phase_effectiveness(pe)
    p3 = chart3_top3_A(reports, summary)
    p4 = chart4_top2_B(reports, summary)
    p5 = chart5_worst2(reports, summary)
    p6 = chart6_deviation(reports)
    html = build_html([p1, p2, p3, p4, p5, p6], summary, pe, dev)
    for p in [p1, p2, p3, p4, p5, p6]:
        if p and os.path.exists(p):
            print(f"  ✓ {os.path.basename(p)} ({os.path.getsize(p)//1024} KB)")
    print(f"  ✓ backtest_charts.html ({os.path.getsize(html)//1024} KB)")


if __name__ == "__main__":
    main()
