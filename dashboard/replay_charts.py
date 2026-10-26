# -*- coding: utf-8 -*-
"""
市场复盘可视化 (replay_charts.py)
生成4张图: 大盘走势+阶段 / 行业热力图 / 热点主线净值 / 板块轮动甘特图
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "dashboard", "replay_charts")

PHASE_COLOR = {"上涨": "#2ca02c", "下跌": "#d62728", "震荡": "#bbbbbb"}


def generate_all(replay):
    """生成全部4张图，返回 {key: path}"""
    os.makedirs(CHART_DIR, exist_ok=True)
    label = replay.label
    paths = {}
    try:
        paths["chart1"] = chart1_benchmark(replay, label)
    except Exception as e:
        paths["chart1_err"] = str(e)
    try:
        paths["chart2"] = chart2_heatmap(replay, label)
    except Exception as e:
        paths["chart2_err"] = str(e)
    try:
        paths["chart3"] = chart3_mainline(replay, label)
    except Exception as e:
        paths["chart3_err"] = str(e)
    try:
        paths["chart4"] = chart4_rotation(replay, label)
    except Exception as e:
        paths["chart4_err"] = str(e)
    try:
        paths["chart5"] = chart5_corr_heatmap(replay, label)
    except Exception as e:
        paths["chart5_err"] = str(e)
    return paths


def chart1_benchmark(replay, label):
    """图1: 大盘走势 + 阶段划分 + 催化剂标注"""
    if replay.benchmark is None:
        return None
    bm = replay.benchmark
    fig, ax = plt.subplots(figsize=(13, 6))
    # 阶段背景
    for ph in (replay.phases or []):
        ax.axvspan(ph["start"], ph["end"], color=PHASE_COLOR.get(ph["type"], "#eee"), alpha=0.18)
    ax.plot(bm["date"], bm["close"].astype(float), color="#1a3a5c", lw=1.8, label="上证指数")
    # 阶段标注
    for ph in (replay.phases or []):
        mid = ph["start"] + (ph["end"] - ph["start"]) / 2
        ax.annotate(f"阶段{ph['idx']}\n{ph['type']}\n{ph['return']:+.1f}%",
                    xy=(mid, ph["end_close"]), fontsize=8, ha="center",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=PHASE_COLOR.get(ph["type"]), alpha=0.85))
    # 催化剂竖线(重要>=4)
    if replay.catalysts is not None:
        for _, c in replay.catalysts.iterrows():
            if c["date"] >= bm["date"].min() and c["date"] <= bm["date"].max():
                imp = int(c["importance"]) if not pd.isna(c["importance"]) else 1
                if imp >= 4:
                    color = "#1a7f37" if c["direction"] == "正面" else ("#cf222e" if c["direction"] == "负面" else "#999")
                    ax.axvline(c["date"], color=color, ls="--", lw=0.8, alpha=0.6)
                    ax.text(c["date"], ax.get_ylim()[1] if False else bm["close"].astype(float).max(),
                            f" {c['event_name'][:10]}", rotation=90, fontsize=6.5, va="top", color=color)
    ax.set_title(f"图1: {label} 大盘走势与阶段划分(背景色:绿=上涨 红=下跌 灰=震荡)")
    ax.set_ylabel("上证指数收盘价")
    ax.grid(alpha=0.25)
    legend = [Patch(facecolor=PHASE_COLOR[k], alpha=0.4, label=k) for k in ["上涨", "下跌", "震荡"]]
    ax.legend(handles=legend + [plt.Line2D([0], [0], color="#1a3a5c", label="上证指数")], loc="upper left", fontsize=9)
    plt.tight_layout()
    p = os.path.join(CHART_DIR, f"{label}_chart_1.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def chart2_heatmap(replay, label):
    """图2: 22行业×各阶段 涨跌幅热力图"""
    if replay.rankings is None:
        return None
    rdf = replay.rankings.sort_values("全期涨跌幅", ascending=False)
    phase_cols = [f"阶段{p['idx']}" for p in (replay.phases or [])]
    cols = ["全期涨跌幅"] + phase_cols
    data = rdf[cols].astype(float).values
    fig, ax = plt.subplots(figsize=(max(7, len(cols) * 2.2), max(8, len(rdf) * 0.42)))
    vmax = max(15, np.nanmax(np.abs(data)) * 0.8)
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_yticks(range(len(rdf)))
    ax.set_yticklabels(rdf["行业"], fontsize=10)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(["全期"] + [f"阶段{p['idx']}" for p in (replay.phases or [])], fontsize=10)
    # 数字标注
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:+.0f}", ha="center", va="center", fontsize=7.5,
                        color="black")
    plt.colorbar(im, ax=ax, label="涨跌幅%")
    ax.set_title(f"图2: {label} 22行业各阶段涨跌幅热力图(深绿=大涨 深红=大跌)")
    plt.tight_layout()
    p = os.path.join(CHART_DIR, f"{label}_chart_2.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def chart3_mainline(replay, label):
    """图3: 热点主线净值 vs 大盘 vs 对照组"""
    if not replay.index_data:
        return None
    hot = replay.identify_hotspots()
    mains = [m["行业"] for m in hot.get("主线", [])][:3]
    # 对照组: 全期涨幅最低的2个
    rdf = replay.rankings.sort_values("全期涨跌幅")
    contrast = list(rdf["行业"].head(2))
    targets = [m for m in mains if m in replay.index_data] + \
              [c for c in contrast if c in replay.index_data and c not in mains]
    if not targets:
        targets = list(replay.index_data.keys())[:4]
    fig, ax = plt.subplots(figsize=(12, 6))
    # 大盘
    if replay.benchmark is not None and len(replay.benchmark):
        bn = replay.benchmark["close"].astype(float)
        ax.plot(replay.benchmark["date"], bn / bn.iloc[0], color="#666", lw=2, ls="--", label="上证指数")
    colors = plt.cm.tab10(np.linspace(0, 1, len(targets)))
    for ind, col in zip(targets, colors):
        df = replay.index_data[ind]
        c = df["close"].astype(float)
        lw = 2.4 if ind in mains else 1.3
        ax.plot(df["date"], c / c.iloc[0], color=col, lw=lw,
                label=f"{ind}{'(主线)' if ind in mains else '(对照)'}")
    ax.axhline(1.0, color="black", lw=0.6, ls=":")
    ax.set_title(f"图3: {label} 热点主线净值 vs 大盘 vs 对照组(归一化)")
    ax.set_ylabel("归一化净值(起点=1)")
    ax.legend(fontsize=8, loc="upper left", ncol=2)
    ax.grid(alpha=0.25)
    plt.tight_layout()
    p = os.path.join(CHART_DIR, f"{label}_chart_3.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def chart4_rotation(replay, label):
    """图4: 板块轮动甘特图 — 各行业滚动5日TOP5时着色"""
    rot = replay.detect_rotation_chain()
    if not rot or not rot["chain"]:
        return None
    chain = rot["chain"]
    # 收集所有行业
    all_inds = sorted({t[0] for c in chain for t in c["leaders"]})
    if not all_inds:
        return None
    # 每个行业在哪些子窗口进TOP3
    active = {ind: [] for ind in all_inds}
    for c in chain:
        leaders = c["leaders"]
        for (ind, ret) in leaders:
            is_top = (ind == leaders[0][0])
            active[ind].append((c["window_start"], c["window_end"], is_top, ret))
    # 按行业全期涨幅排序(便于观察)
    order = sorted(all_inds, key=lambda x: -max((r[3] for r in active[x]), default=0))
    fig, (ax, ax_bm) = plt.subplots(2, 1, figsize=(13, max(6, len(order) * 0.4 + 2)),
                                    gridspec_kw={"height_ratios": [len(order), 1]}, sharex=True)
    for i, ind in enumerate(order):
        for (s, e, is_top, ret) in active[ind]:
            # 颜色深浅反映涨幅强度
            norm = max(-1, min(1, (ret or 0) / 15))
            if is_top:
                color = (0.1, 0.5, 0.2, 0.9) if norm > 0.3 else (0.4, 0.7, 0.4, 0.7)
            else:
                color = (1.0, 0.7, 0.3, 0.6)
            ax.barh(i, max((e - s).days, 3), left=s, height=0.6, color=color, edgecolor="white")
    # 切换事件竖虚线
    for s in replay.detect_rotation_chain().get("switch_events", []):
        if s["enter"]:
            ax.axvline(s["date"], color="#6a3d9a", ls=":", lw=0.9, alpha=0.7)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=9)
    ax.set_title(f"图4: {label} 板块轮动甘特图(深绿=领涨大涨 浅绿=领涨小涨 橙=TOP3; 紫虚线=切换)")
    ax.grid(axis="x", alpha=0.3)
    legend = [Patch(facecolor=(0.1, 0.5, 0.2), label="领涨大涨"),
              Patch(facecolor=(0.4, 0.7, 0.4), label="领涨小涨"),
              Patch(facecolor=(1.0, 0.7, 0.3), label="进TOP3")]
    ax.legend(handles=legend, fontsize=8, loc="upper right")
    # 底部大盘缩略
    if replay.benchmark is not None and len(replay.benchmark):
        ax_bm.plot(replay.benchmark["date"], replay.benchmark["close"].astype(float),
                   color="#1a3a5c", lw=1.2)
        ax_bm.set_ylabel("上证")
        ax_bm.grid(alpha=0.3)
        ax_bm.set_title("大盘走势参照", fontsize=9)
    plt.tight_layout()
    p = os.path.join(CHART_DIR, f"{label}_chart_4.png")
    plt.savefig(p, dpi=110); plt.close()
    return p


def chart5_corr_heatmap(replay, label):
    """图5: 22行业日收益率相关系数热力图(按产业链分组排序)"""
    if not replay.index_data:
        return None
    import pandas as pd
    # 按产业链分组排列行业顺序
    chain_order = []
    for members in [
        ["计算机设备", "软件开发", "通信设备", "传媒", "电子", "半导体", "消费电子"],
        ["能源金属", "电池", "光伏设备", "风电设备", "电力设备"],
        ["煤炭", "基础化工", "有色金属", "贵金属"],
        ["非银金融", "房地产"],
        ["国防军工", "食品饮料", "汽车零部件", "医疗器械"],
    ]:
        for m in members:
            if m in replay.index_data and m not in chain_order:
                chain_order.append(m)
    avail = [m for m in chain_order if m in replay.index_data]
    if len(avail) < 3:
        return None
    rets = pd.DataFrame({m: replay.index_data[m]["close"].astype(float).pct_change()
                         for m in avail}).dropna(how="all")
    corr = rets.corr().values
    fig, ax = plt.subplots(figsize=(11, 10))
    im = ax.imshow(corr, cmap="RdYlGn", vmin=-1, vmax=1)
    ax.set_xticks(range(len(avail))); ax.set_yticks(range(len(avail)))
    ax.set_xticklabels(avail, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(avail, fontsize=9)
    for i in range(len(avail)):
        for j in range(len(avail)):
            ax.text(j, i, f"{corr[i,j]:.2f}", ha="center", va="center", fontsize=6.5,
                    color="white" if abs(corr[i, j]) > 0.6 else "black")
    plt.colorbar(im, ax=ax, label="日收益率相关系数")
    ax.set_title(f"图5: {label} 22行业相关系数热力图(按产业链分组: TMT→新能源→周期→金融→其他)")
    plt.tight_layout()
    p = os.path.join(CHART_DIR, f"{label}_chart_5.png")
    plt.savefig(p, dpi=110); plt.close()
    return p
