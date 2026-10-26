#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年度深度叙事报告生成器(券商研报式)
====================================
按时间顺序讲清楚全年主线故事,四章:
  一、全年鸟瞰(31×52 热力图 + 上证周线 + 全年统计)
  二、逐段主线深度叙事(背景+逐周明细+横向对比+迷你图 + 切换过渡分析)
  三、全年切换全景图(接力时间轴 + 切换矩阵)
  四、纵向对比(与其他年份相似切换/主线行业跨年矩阵)

纯 HTML/CSS/SVG,不依赖外部库。暗色科技风。
"""

import os
from collections import defaultdict

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw_data")
REPORT_DIR = os.path.join(BASE_DIR, "dashboard", "replay_reports")
os.makedirs(REPORT_DIR, exist_ok=True)

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
_ERA = {
    2016: ("供给侧改革", "#e67e22", "去产能+PPP+房地产去库存,熔断后慢牛修复"),
    2017: ("核心资产崛起", "#2ecc71", "外资流入+消费升级+供给侧红利,白马龙头行情"),
    2018: ("去杠杆熊市", "#e74c3c", "中美贸易战+金融去杠杆,全年单边下跌"),
    2019: ("科技牛启动", "#3498db", "5G商用+半导体国产替代+科创板,成长股领涨"),
    2020: ("疫情与流动性", "#9b59b6", "COVID-19冲击+全球放水,消费/新能源/核心资产轮动"),
    2021: ("碳中和新能源", "#1abc9c", "双碳政策+锂电光伏+周期涨价,新能源年度主线"),
    2022: ("地缘与衰退", "#e74c3c", "俄乌冲突+美联储激进加息+地产暴雷,熊市防御"),
    2023: ("AI元年", "#3498db", "ChatGPT引发全球AI浪潮,算力与TMT板块全面爆发"),
    2024: ("AI深化+924行情", "#f39c12", "AI应用扩散+高股息防御+924政策反转行情"),
    2025: ("AI应用落地", "#2ecc71", "DeepSeek催化+人形机器人+关税冲击+有色金属"),
}
_LEVEL_COLORS = {"长期主线": "#f1c40f", "中期主线": "#3498db", "短期热点": "#7f8c8d"}


def _hex(h):
    h = h.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def _ret_color(ret):
    """周涨跌幅 → 背景色(深红>5/浅红0-5/浅绿0至-5/深绿<-5)。"""
    if ret is None or pd.isna(ret):
        return "#1a2030"
    if ret >= 5:
        return "#c0392b"
    if ret > 0:
        return f"rgba(231,76,60,{0.25 + min(ret/5,1)*0.6})"
    if ret == 0:
        return "#2a3555"
    if ret > -5:
        return f"rgba(46,204,113,{0.25 + min(-ret/5,1)*0.6})"
    return "#16a085"


def _load_data(year):
    """加载该年所需的全部数据。"""
    ml = pd.read_csv(os.path.join(RAW_DIR, "2016_2025_mainlines_v3.csv"))
    ml = ml[(ml["年份"] == year) & (ml["级别"].isin(["中期主线", "长期主线"]))].sort_values(["开始周", "行业"])
    sw = pd.read_csv(os.path.join(RAW_DIR, "2016_2025_switch_signals.csv"))
    sw = sw[sw["年份"] == year].sort_values("切换周")
    cat = pd.read_csv(os.path.join(RAW_DIR, "catalyst_events_full.csv"))
    cat["日期"] = pd.to_datetime(cat["日期"], errors="coerce")
    cat = cat[cat["日期"].dt.year == year]
    cyc = pd.read_csv(os.path.join(RAW_DIR, "sw31_cycle_phases.csv"))
    cyc_map = dict(zip(cyc["行业名称"], cyc["产能周期阶段"]))
    # 周度(31行业)
    d = pd.read_csv(os.path.join(RAW_DIR, "sw31_daily_all.csv"))
    d["日期"] = pd.to_datetime(d["日期"], errors="coerce")
    d = d[d["日期"].dt.year == year].copy()
    d["周"] = d["日期"].dt.isocalendar().week.astype(int)
    wk = d.groupby(["行业名称", "周"]).agg(
        周开盘=("开盘", "first"), 周收盘=("收盘", "last"),
        周成交额=("成交额_亿元", "sum")).reset_index()
    wk["周涨跌幅"] = np.where(wk["周开盘"] > 0, (wk["周收盘"] / wk["周开盘"] - 1) * 100, 0)
    wk["周排名"] = wk.groupby("周")["周涨跌幅"].rank(ascending=False, method="min").astype(int)
    wk = wk.sort_values(["行业名称", "周"])
    wk["cum"] = (1 + wk["周涨跌幅"] / 100).groupby(wk["行业名称"]).cumprod()
    wk["累计涨幅"] = (wk["cum"] - 1) * 100
    wk.drop(columns=["cum", "周开盘", "周收盘"], inplace=True)
    # 上证周线
    sh = pd.read_csv(os.path.join(RAW_DIR, "broad_index_daily.csv"))
    sh = sh[sh["index_name"] == "上证指数"].copy()
    sh["date"] = pd.to_datetime(sh["date"], errors="coerce")
    sh = sh[sh["date"].dt.year == year].copy()
    sh["周"] = sh["date"].dt.isocalendar().week.astype(int)
    shw = sh.groupby("周").agg(周开盘=("open", "first"), 周收盘=("close", "last"),
                               周涨跌=("change_pct", "sum")).reset_index().sort_values("周")
    shw["周涨跌幅"] = np.where(shw["周开盘"] > 0, (shw["周收盘"] / shw["周开盘"] - 1) * 100, 0)
    return ml, sw, cat, cyc_map, wk, shw


# ── 复用 chronicle 的逐周明细逻辑 ──
def _weekly_rows(wk_df, ind, start_w, end_w, active_weeks):
    """与 chronicle._weekly_for_mainline 等价的本地实现(避免跨模块依赖)。"""
    rows = []
    sub = wk_df[wk_df["行业名称"] == ind]
    smap = {int(r["周"]): r for _, r in sub.iterrows()}
    active_set = set(active_weeks)
    peak_ret = sub["周涨跌幅"].max() if not sub.empty else 0
    peak_amt = sub["周成交额"].max() if not sub.empty else 0
    prev_ret = prev_amt = prev_rank = None
    cnt = 0
    for w in range(start_w, end_w + 1):
        r = smap.get(w)
        is_active = w in active_set
        if r is None:
            rows.append({"周": w, "周涨跌幅": None, "累计涨幅": None,
                         "周成交额": None, "周排名": None, "活跃": False, "阶段": "间断"})
            continue
        ret = float(r["周涨跌幅"]); amt = float(r["周成交额"]); rank = int(r["周排名"])
        cum = float(r["累计涨幅"])
        if not is_active:
            stage = "间断"
        elif cnt < 2 and is_active:
            stage = "启动" if ret > 0 else "伪启动"
            if ret > 0:
                cnt += 1
        elif (ret == peak_ret and peak_ret > 0) or (amt == peak_amt and amt > 0):
            stage = "高潮"; cnt += 1
        elif prev_ret is not None and (ret < prev_ret or (prev_amt and amt < prev_amt)):
            stage = "衰退" if (ret < 0 or rank > 10) else "放缓"; cnt += 1
        elif ret < 0 or rank > 10:
            stage = "衰退"; cnt += 1
        else:
            stage = "加速"; cnt += 1
        rows.append({"周": w, "周涨跌幅": ret, "累计涨幅": cum, "周成交额": amt,
                     "周排名": rank, "活跃": is_active, "阶段": stage})
        prev_ret, prev_amt, prev_rank = ret, amt, rank
    return rows


def _mini_svg(rows, width=400, height=120):
    pts = [r for r in rows if r["周涨跌幅"] is not None]
    if len(pts) < 2:
        return '<div style="color:#5a6478;font-size:12px;padding:8px;">数据不足</div>'
    n = len(pts)
    rets = [r["周涨跌幅"] for r in pts]; amts = [r["周成交额"] for r in pts]
    rmin, rmax = min(rets + [0]), max(rets + [0])
    amax = max(amts) if max(amts) > 0 else 1
    pl, pr, pt, pb = 28, 30, 10, 16
    pw, ph = width - pl - pr, height - pt - pb
    xa = lambda i: pl + (i / max(n - 1, 1)) * pw
    yr = lambda v: pt + (1 - (v - rmin) / (rmax - rmin if rmax != rmin else 1)) * ph
    ya = lambda v: pt + ph - (v / amax) * (ph * 0.6)
    zy = yr(0); pk = rets.index(max(rets))
    dec = next((i for i in range(1, n) if rets[i] < 0 and rets[i - 1] > 0), None)
    s = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:{width}px;">']
    for i, a in enumerate(amts):
        bh = (a / amax) * (ph * 0.6)
        s.append(f'<rect x="{xa(i)-3:.1f}" y="{pt+ph-bh:.1f}" width="6" height="{bh:.1f}" fill="#3a4660" opacity="0.5"/>')
    s.append(f'<line x1="{pl}" y1="{zy:.1f}" x2="{width-pr}" y2="{zy:.1f}" stroke="#2a3555" stroke-width="0.5" stroke-dasharray="2,2"/>')
    s.append('<polyline points="' + " ".join(f"{xa(i):.1f},{yr(rets[i]):.1f}" for i in range(n)) + '" fill="none" stroke="#f1c40f" stroke-width="1.5"/>')
    for i in range(n):
        s.append(f'<circle cx="{xa(i):.1f}" cy="{yr(rets[i]):.1f}" r="1.8" fill="{"#e74c3c" if rets[i]>=0 else "#2ecc71"}"/>')
    s.append(f'<text x="{xa(pk):.1f}" y="{yr(rets[pk])-5:.1f}" fill="#f1c40f" font-size="11" text-anchor="middle">★</text>')
    if dec is not None:
        s.append(f'<text x="{xa(dec):.1f}" y="{yr(rets[dec])-5:.1f}" fill="#e74c3c" font-size="10" text-anchor="middle">▼</text>')
    s.append(f'<text x="4" y="{pt+8:.0f}" fill="#8892a4" font-size="9">{rmax:.0f}%</text>')
    s.append(f'<text x="4" y="{pt+ph:.0f}" fill="#8892a4" font-size="9">{rmin:.0f}%</text>')
    s.append(f'<text x="{width-pr+2:.0f}" y="{pt+ph:.0f}" fill="#8892a4" font-size="9">{amax:.0f}亿</text>')
    return "".join(s) + '</svg>'


def _weekly_table_html(rows):
    H = ['<table class="wktbl"><thead><tr>',
         '<th>周</th><th>周涨跌幅</th><th>累计涨幅</th><th>成交额(亿)</th>',
         '<th>成交额变化</th><th>排名</th><th>排名变化</th><th>阶段</th></tr></thead><tbody>']
    pa = pr = None
    for r in rows:
        if r["周涨跌幅"] is None:
            H.append(f'<tr class="gap"><td>第{r["周"]}周</td><td colspan="7" style="color:#3a4660;">⬜ 间断</td></tr>')
            pa = pr = None; continue
        rc = "pos" if r["周涨跌幅"] >= 0 else "neg"
        cc = "pos" if r["累计涨幅"] >= 0 else "neg"
        ac = "—"
        if pa and pa > 0:
            ch = (r["周成交额"] / pa - 1) * 100
            ac = f'<span class="{"pos" if ch>=0 else "neg"}">{ch:+.1f}%</span>'
        rkc = "—"
        if pr is not None:
            dd = pr - r["周排名"]
            rkc = f'<span class="pos">↑{dd}</span>' if dd > 0 else (f'<span class="neg">↓{-dd}</span>' if dd < 0 else "—")
        ic = {"启动": ("🟢", "#2ecc71"), "加速": ("🟢", "#2ecc71"), "高潮": ("🔴", "#e74c3c"),
              "放缓": ("🟡", "#f39c12"), "衰退": ("⚫", "#95a5a6"),
              "间断": ("⬜", "#3a4660"), "伪启动": ("⚠️", "#5a6478")}.get(r["阶段"], ("", "#888"))
        H.append(f'<tr><td>第{r["周"]}周</td><td class="{rc}">{r["周涨跌幅"]:+.1f}%</td>'
                 f'<td class="{cc}">{r["累计涨幅"]:+.1f}%</td><td>{r["周成交额"]:.0f}</td>'
                 f'<td>{ac}</td><td>第{r["周排名"]}名</td><td>{rkc}</td>'
                 f'<td style="color:{ic[1]};">{ic[0]} {r["阶段"]}</td></tr>')
        pa, pr = r["周成交额"], r["周排名"]
    H.append('</tbody></table>')
    return "".join(H)


def _switch_for(ml, yr_sw):
    """挂在该主线后的接力切换。"""
    ind = str(ml.get("行业", "")); end_w = ml.get("结束周", 10**9)
    cands = [s for s in yr_sw if str(s.get("旧主线", "")) == ind and s.get("切换周", 10**9) >= end_w]
    if not cands:
        cands = [s for s in yr_sw if str(s.get("旧主线", "")) == ind]
    if not cands:
        return None
    cands.sort(key=lambda s: abs(s.get("切换周", 0) - end_w))
    return cands[0]


def generate_deep_narrative(year=2023):
    ml, sw, cat, cyc_map, wk, shw = _load_data(year)
    if ml.empty:
        print(f"[ERROR] {year} 无主线数据"); return None
    era_name, era_color, era_desc = _ERA.get(year, (str(year), "#888", ""))

    # 主线行业集合(用于热力图高亮)
    ml_inds = set(ml["行业"].tolist())
    # 主线周区间(行业 -> list of (start_w, end_w))
    ml_spans = defaultdict(list)
    for _, r in ml.iterrows():
        ml_spans[r["行业"]].append((int(r["开始周"]), int(r["结束周"])))

    weeks = sorted(wk["周"].unique())
    all_inds = sorted(wk["行业名称"].unique())
    # 31×52 涨跌幅矩阵
    pivot = wk.pivot_table(index="行业名称", columns="周", values="周涨跌幅")
    # 全年涨跌(用于横向对比/最强最弱)
    yr_ret = wk.groupby("行业名称").agg(累计=("累计涨幅", "last"), 总成交=("周成交额", "sum"))
    best = yr_ret["累计"].idxmax(); worst = yr_ret["累计"].idxmin()

    H = []
    H.append(f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{year} 主线深度叙事</title>
<style>
:root{{--bg:#0a0e17;--card:#131a2b;--text:#e8eaf0;--t2:#8892a4;--t3:#5a6478;
--gold:#f1c40f;--blue:#3498db;--green:#2ecc71;--red:#e74c3c;--orange:#f39c12;--border:#1e2a42;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.75;padding:20px;}}
.c{{max-width:1300px;margin:0 auto;}}
.hd{{background:linear-gradient(135deg,#0f1629,#1a2a4a,#0d1b2a);border:1px solid var(--border);border-radius:16px;padding:36px;margin-bottom:24px;text-align:center;}}
.hd h1{{font-size:30px;background:linear-gradient(90deg,var(--gold),var(--orange));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;}}
.hd .s{{color:var(--t2);font-size:15px;}}
.ch{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:28px;margin-bottom:24px;}}
.ch h2{{font-size:22px;color:var(--gold);margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border);}}
.ch h3{{font-size:17px;color:var(--blue);margin:20px 0 10px;}}
.stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0;}}
.stat{{background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center;}}
.stat .v{{font-size:26px;font-weight:700;}}.stat .l{{color:var(--t2);font-size:12px;}}
/* 热力图 */
.hm-wrap{{display:flex;gap:16px;flex-wrap:wrap;}}
.hm{{overflow-x:auto;flex:1;min-width:600px;}}
.hm table{{border-collapse:collapse;font-size:9px;}}
.hm th,.hm td{{width:16px;height:16px;text-align:center;border:1px solid rgba(255,255,255,0.03);}}
.hm th{{color:var(--t2);font-weight:600;height:20px;font-size:8px;}}
.hm td.ind{{width:70px;text-align:right;padding-right:5px;color:var(--t2);font-size:10px;}}
.hm td.mlcell{{box-shadow:inset 0 0 0 2px var(--gold);}}
.legend{{display:flex;gap:8px;font-size:10px;color:var(--t2);align-items:center;margin-top:8px;flex-wrap:wrap;}}
.lg-box{{width:14px;height:14px;border-radius:2px;display:inline-block;margin-right:3px;}}
/* 逐周明细表 */
.wktbl{{width:100%;border-collapse:collapse;font-size:12px;margin:10px 0;}}
.wktbl th{{background:rgba(255,255,255,0.05);padding:6px;text-align:center;color:var(--t2);font-weight:600;}}
.wktbl td{{padding:5px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.04);}}
.wktbl tr.gap td{{color:#3a4660;font-style:italic;}}
.wktbl .pos{{color:var(--red);}}.wktbl .neg{{color:var(--green);}}
/* 横向条形对比 */
.bars{{margin:10px 0;}}
.bar-row{{display:flex;align-items:center;margin:3px 0;font-size:11px;}}
.bar-name{{width:70px;text-align:right;padding-right:6px;color:var(--t2);flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.bar-track{{flex:1;position:relative;height:16px;background:rgba(255,255,255,0.02);border-radius:3px;}}
.bar-fill{{position:absolute;height:14px;top:1px;border-radius:2px;display:flex;align-items:center;padding:0 4px;font-size:9px;color:#fff;}}
.bar-mid{{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#2a3555;}}
.bar-row.hl .bar-name{{color:var(--gold);font-weight:700;}}
/* 切换过渡 */
.sw-box{{background:rgba(241,196,15,0.04);border:1px solid rgba(241,196,15,0.15);border-radius:10px;padding:16px;margin:16px 0;}}
.sw-title{{font-size:15px;font-weight:700;color:var(--gold);margin-bottom:10px;}}
.cmp{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0;}}
@media(max-width:768px){{.cmp{{grid-template-columns:1fr;}}}}
.cmpt{{width:100%;border-collapse:collapse;font-size:11px;}}
.cmpt th{{color:var(--t3);font-weight:600;padding:3px;}}.cmpt td{{padding:3px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.04);}}
.cmpt .pos{{color:var(--red);}}.cmpt .neg{{color:var(--green);}}
.sig-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px;}}
@media(max-width:768px){{.sig-grid{{grid-template-columns:1fr;}}}}
.sig-bx{{padding:10px;border-radius:8px;font-size:12px;}}
.sig-bx.t{{background:rgba(231,76,60,0.06);border:1px solid rgba(231,76,60,0.15);}}
.sig-bx.c{{background:rgba(52,152,219,0.06);border:1px solid rgba(52,152,219,0.15);}}
.sig-bx.f{{background:rgba(46,204,113,0.06);border:1px solid rgba(46,204,113,0.15);}}
.sig-bx h4{{font-size:12px;margin-bottom:4px;}}.sig-bx h4.t{{color:var(--red);}}.sig-bx h4.c{{color:var(--blue);}}.sig-bx h4.f{{color:var(--green);}}
.sig-bx .d{{color:var(--t2);font-size:11px;line-height:1.6;}}
/* 接力时间轴 */
.relay{{position:relative;margin:16px 0;}}
.relay-row{{display:flex;align-items:center;margin:4px 0;font-size:11px;}}
.relay-name{{width:70px;text-align:right;padding-right:8px;color:var(--t2);flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.relay-track{{flex:1;position:relative;height:18px;background:rgba(255,255,255,0.02);border-radius:3px;}}
.relay-bar{{position:absolute;height:14px;top:2px;border-radius:2px;display:flex;align-items:center;justify-content:center;font-size:9px;color:#000;font-weight:600;overflow:hidden;white-space:nowrap;}}
/* 矩阵表 */
.mtx{{width:100%;border-collapse:collapse;font-size:12px;margin:12px 0;}}
.mtx th{{background:rgba(255,255,255,0.05);padding:8px;text-align:center;color:var(--t2);}}
.mtx td{{padding:7px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.04);}}
.badge{{padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600;}}
.b-long{{background:rgba(241,196,15,0.2);color:var(--gold);}}.b-mid{{background:rgba(52,152,219,0.2);color:var(--blue);}}
.mini{{background:rgba(255,255,255,0.02);border-radius:6px;padding:6px;margin:8px 0;}}
.note{{background:rgba(52,152,219,0.06);border-left:3px solid var(--blue);padding:12px 16px;border-radius:6px;font-size:13px;color:var(--t2);margin:10px 0;}}
.ft{{text-align:center;padding:24px;color:var(--t3);font-size:12px;}}
.cat{{display:inline-block;padding:2px 7px;border-radius:6px;font-size:10px;background:rgba(243,156,18,0.15);color:var(--orange);margin:2px 3px 2px 0;}}
</style></head><body><div class="c">
""")

    # ════════ 第一章:全年鸟瞰 ════════
    H.append(f"""
<div class="hd"><h1>📖 {year}年 A股主线深度叙事</h1>
<div class="s">{era_name} · {era_desc}</div>
<div class="s" style="margin-top:6px;font-size:13px;color:var(--t3);">{len(ml)}段中期/长期主线 · {len(sw)}次接力切换 · 31行业×{len(weeks)}周</div></div>
""")

    H.append(f'<div class="ch"><h2>第一章 · 全年鸟瞰</h2>')
    # 全年统计
    H.append(f"""<div class="stat-grid">
  <div class="stat"><div class="v" style="color:var(--gold)">{len(ml)}</div><div class="l">主线段数</div></div>
  <div class="stat"><div class="v" style="color:var(--blue)">{len(sw)}</div><div class="l">接力切换</div></div>
  <div class="stat"><div class="v" style="color:var(--red)">{best}</div><div class="l">最强行业 +{yr_ret.loc[best,"累计"]:.1f}%</div></div>
  <div class="stat"><div class="v" style="color:var(--green)">{worst}</div><div class="l">最弱行业 {yr_ret.loc[worst,"累计"]:.1f}%</div></div>
</div>""")
    # 热力图 + 上证周线
    H.append('<div class="hm-wrap"><div class="hm"><h3>🌡️ 31行业 × 周涨跌幅热力图(金框=主线周)</h3><table><thead><tr><th></th>')
    for w in weeks:
        H.append(f'<th>{w}</th>')
    H.append('</tr></thead><tbody>')
    for ind in all_inds:
        ind_style = ' style="color:var(--gold);font-weight:700;"' if ind in ml_inds else ""
        H.append(f'<tr><td class="ind"{ind_style}>{ind}</td>')
        spans = ml_spans.get(ind, [])
        for w in weeks:
            v = pivot.loc[ind, w] if (ind in pivot.index and w in pivot.columns) else None
            is_ml = any(s <= w <= e for s, e in spans)
            ml_cls = ' class="mlcell"' if is_ml else ""
            if v is not None and not pd.isna(v):
                tip = f"{ind} 第{w}周 {v:+.1f}%"
            else:
                tip = f"{ind} 第{w}周 无数据"
            H.append(f'<td style="background:{_ret_color(v)};"{ml_cls} title="{tip}"></td>')
        H.append('</tr>')
    H.append('</tbody></table>')
    H.append('<div class="legend">'
             '<span><span class="lg-box" style="background:#c0392b;"></span>>5%</span>'
             '<span><span class="lg-box" style="background:rgba(231,76,60,0.6);"></span>0~5%</span>'
             '<span><span class="lg-box" style="background:rgba(46,204,113,0.6);"></span>-5~0%</span>'
             '<span><span class="lg-box" style="background:#16a085;"></span><-5%</span>'
             '<span><span class="lg-box" style="background:transparent;border:2px solid var(--gold);"></span>主线周</span></div>')
    H.append('</div>')

    # 上证周线 SVG
    sh_rets = [float(shw.loc[shw["周"] == w, "周涨跌幅"].iloc[0]) if w in shw["周"].values else 0 for w in weeks]
    sh_close = [float(shw.loc[shw["周"] == w, "周收盘"].iloc[0]) if w in shw["周"].values else None for w in weeks]
    valid = [(w, c) for w, c in zip(weeks, sh_close) if c is not None]
    if valid:
        W, HH = 380, 160
        pl, pr, pt, pb = 36, 12, 16, 24
        pw, ph = W - pl - pr, HH - pt - pb
        cs = [c for _, c in valid]; cmin, cmax = min(cs), max(cs)
        rng = cmax - cmin if cmax != cmin else 1
        xa = lambda i: pl + (i / max(len(valid) - 1, 1)) * pw
        ya = lambda c: pt + (1 - (c - cmin) / rng) * ph
        line = " ".join(f"{xa(i):.1f},{ya(c):.1f}" for i, (_, c) in enumerate(valid))
        H.append(f'<div style="flex:0 0 400px;"><h3>📈 上证指数周线</h3>'
                 f'<svg viewBox="0 0 {W} {HH}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:{W}px;">'
                 f'<polyline points="{line}" fill="none" stroke="#3498db" stroke-width="1.5"/>')
        for i, (w, c) in enumerate(valid):
            r = sh_rets[weeks.index(w)] if w in weeks else 0
            H.append(f'<circle cx="{xa(i):.1f}" cy="{ya(c):.1f}" r="1.5" fill="{"#e74c3c" if r>=0 else "#2ecc71"}"/>')
        H.append(f'<text x="4" y="{pt+8:.0f}" fill="#8892a4" font-size="9">{cmax:.0f}</text>'
                 f'<text x="4" y="{pt+ph:.0f}" fill="#8892a4" font-size="9">{cmin:.0f}</text>'
                 f'<text x="{pl:.0f}" y="{HH-6:.0f}" fill="#5a6478" font-size="9">第{valid[0][0]}周</text>'
                 f'<text x="{W-pr:.0f}" y="{HH-6:.0f}" fill="#5a6478" font-size="9" text-anchor="end">第{valid[-1][0]}周</text>'
                 f'</svg></div>')
    H.append('</div></div>')  # hm-wrap, ch

    # ════════ 第二章:逐段主线深度叙事 ════════
    H.append(f'<div class="ch"><h2>第二章 · 逐段主线深度叙事</h2>')
    for idx, m in ml.iterrows():
        ind = m["行业"]; level = m["级别"]; cum = m["累计涨幅"]; span = m["总跨度周数"]
        aw = m["活跃周数"]; sw_ = int(m["开始周"]); ew = int(m["结束周"])
        color = _LEVEL_COLORS.get(level, "#888")
        grp = _SECTOR_GROUP.get(ind, "其他"); cyc = cyc_map.get(ind, "未标注")
        try:
            active = [int(x) for x in str(m.get("周列表", "[]")).strip("[]").split(",") if x.strip()]
        except Exception:
            active = []
        rows = _weekly_rows(wk, ind, sw_, ew, active)

        # A. 启动背景(催化事件匹配)
        cats_hit = []
        for _, c in cat.iterrows():
            cinds = [x.strip() for x in str(c.get("关联行业", "")).split(";") if x.strip()]
            if ind in cinds:
                cats_hit.append((c["日期"], c.get("事件名称", "")))
        cats_hit.sort()
        bg = f'{era_name}期间,{ind}({_SECTOR_GROUP.get(ind,"")}板块)作为{level}启动'
        if cats_hit:
            bg += f",关联催化:{cats_hit[0][1]}" + (f" 等{len(cats_hit)}个事件" if len(cats_hit) > 1 else "")
        else:
            bg += ",无明显单一催化,属行业自发景气或资金轮动"

        H.append(f'<h3 id="ml{idx}">{"🥇" if level=="长期主线" else "🥈"} {ind} · {level} · 第{sw_}-{ew}周 · 累计{cum:+.1f}%</h3>')
        H.append(f'<div class="note"><strong>启动背景:</strong>{bg}。'
                 f'产能周期:<strong>{cyc}</strong>,跨度{span}周(活跃{aw}周),板块归属{grp}。</div>')

        # D. 迷你折线图
        H.append(f'<div class="mini">{_mini_svg(rows)}</div>')
        # B. 逐周明细表(默认展开)
        H.append(f'<details open><summary style="cursor:pointer;color:var(--blue);font-size:13px;">📋 逐周明细(共{len(rows)}周)</summary>{_weekly_table_html(rows)}</details>')

        # C. 同期横向对比
        H.append(f'<details open><summary style="cursor:pointer;color:var(--blue);font-size:13px;margin-top:8px;">📊 同期31行业横向对比(第{sw_}-{ew}周累计涨幅)</summary><div class="bars">')
        seg = wk[(wk["周"] >= sw_) & (wk["周"] <= ew)]
        seg_ret = seg.groupby("行业名称")["累计涨幅"].apply(
            lambda x: (np.prod(1 + seg.loc[x.index, "周涨跌幅"] / 100) - 1) * 100 if len(x) else 0)
        mx = max(abs(seg_ret).max(), 1)
        for name in seg_ret.sort_values(ascending=False).index:
            v = seg_ret[name]
            hl = " hl" if name == ind else ""
            wd = abs(v) / mx * 50
            if v >= 0:
                H.append(f'<div class="bar-row{hl}"><div class="bar-name">{name}</div><div class="bar-track"><div class="bar-mid"></div>'
                         f'<div class="bar-fill" style="left:50%;width:{wd:.1f}%;background:#e74c3c;">{v:+.1f}%</div></div></div>')
            else:
                H.append(f'<div class="bar-row{hl}"><div class="bar-name">{name}</div><div class="bar-track"><div class="bar-mid"></div>'
                         f'<div class="bar-fill" style="right:50%;width:{wd:.1f}%;background:#2ecc71;">{v:+.1f}%</div></div></div>')
        H.append('</div></details>')

        # 切换过渡 E/F/G
        sw_rec = _switch_for(m, sw.to_dict("records"))
        if sw_rec:
            new_ind = sw_rec.get("新主线", "")
            new_lvl = sw_rec.get("新_级别", "")
            top_sc = sw_rec.get("旧_见顶信号强度", 0); top_txt = sw_rec.get("旧_见顶信号", "")
            ferm_sc = sw_rec.get("新_发酵信号强度", 0); ferm_txt = sw_rec.get("新_发酵信号", "")
            cw = sw_rec.get("交叉窗口周数", 0); ct = sw_rec.get("交叉类型", "")
            swk = int(sw_rec.get("切换周", ew))
            og = _SECTOR_GROUP.get(ind, "其他"); ng = _SECTOR_GROUP.get(new_ind, "其他")
            H.append(f'<div class="sw-box"><div class="sw-title">🔄 接力切换:{ind} → {new_ind}'
                     f'<span style="font-size:12px;color:var(--t2);font-weight:400;">({"跨风格" if og!=ng else "同风格"}: {og}→{ng},第{swk}周)</span></div>')
            # E. 前后4周对比
            old_rows = _weekly_rows(wk, ind, max(1, swk - 5), swk, list(range(max(1, swk - 5), swk + 1)))
            new_rows = _weekly_rows(wk, new_ind, swk, swk + 5, list(range(swk, swk + 6)))
            old4 = [r for r in old_rows if r["周涨跌幅"] is not None][-4:]
            new4 = [r for r in new_rows if r["周涨跌幅"] is not None][:4]

            def _col(rs, title):
                o = [f'<div style="font-size:11px;color:var(--t2);text-align:center;margin-bottom:4px;">{title}</div>'
                     f'<table class="cmpt"><thead><tr><th>周</th><th>涨幅</th><th>成交额</th><th>排名</th></tr></thead><tbody>']
                prk = None
                for r in rs:
                    rc = "pos" if r["周涨跌幅"] >= 0 else "neg"
                    note = ""
                    if prk is not None:
                        dd = prk - r["周排名"]
                        note = f' <span class="pos">↑{dd}</span>' if dd > 0 else (f' <span class="neg">↓{-dd}</span>' if dd < 0 else "")
                    o.append(f'<tr><td>第{r["周"]}周</td><td class="{rc}">{r["周涨跌幅"]:+.1f}%</td><td>{r["周成交额"]:.0f}</td><td>第{r["周排名"]}名{note}</td></tr>')
                    prk = r["周排名"]
                o.append('</tbody></table>')
                return "".join(o)
            H.append(f'<div class="cmp">{_col(old4, f"旧·{ind} 末4周")}{_col(new4, f"新·{new_ind} 初4周")}</div>')
            # F. 切换周31行业快照(横向条形)
            snap = wk[wk["周"] == swk].sort_values("周涨跌幅", ascending=False) if swk in wk["周"].values else pd.DataFrame()
            if not snap.empty:
                H.append('<details><summary style="cursor:pointer;color:var(--blue);font-size:12px;">🔍 切换周(第{}周)31行业涨跌幅快照</summary><div class="bars">'.format(swk))
                mx2 = max(abs(snap["周涨跌幅"]).max(), 1)
                for _, r in snap.iterrows():
                    v = r["周涨跌幅"]; nm = r["行业名称"]
                    hl = " hl" if nm in (ind, new_ind) else ""
                    wd = abs(v) / mx2 * 50
                    if v >= 0:
                        H.append(f'<div class="bar-row{hl}"><div class="bar-name">{nm}</div><div class="bar-track"><div class="bar-mid"></div><div class="bar-fill" style="left:50%;width:{wd:.1f}%;background:#e74c3c;">{v:+.1f}%</div></div></div>')
                    else:
                        H.append(f'<div class="bar-row{hl}"><div class="bar-name">{nm}</div><div class="bar-track"><div class="bar-mid"></div><div class="bar-fill" style="right:50%;width:{wd:.1f}%;background:#2ecc71;">{v:+.1f}%</div></div></div>')
                H.append('</div></details>')
            # G. 信号汇总
            cross_desc = f"重叠{cw:.0f}周({ct})" if cw and cw > 0 else (f"突然切换({ct})" if "突然" in str(ct) else f"{ct},{cw:.0f}周")
            top_html = top_txt.replace(" | ", "<br>") if "无明显" not in str(top_txt) else "无显著见顶征兆"
            ferm_html = ferm_txt.replace(" | ", "<br>") if "无明显" not in str(ferm_txt) else "突发启动型"
            sc = lambda s: "background:rgba(231,76,60,0.2);color:var(--red)" if s >= 3 else ("background:rgba(243,156,18,0.2);color:var(--orange)" if s >= 2 else "background:rgba(149,165,166,0.15);color:var(--t3)")
            H.append(f'<div class="sig-grid">'
                     f'<div class="sig-bx t"><h4 class="t">⚠️ 见顶信号 <span style="padding:1px 6px;border-radius:8px;font-size:10px;{sc(top_sc)}">{top_sc}项</span></h4><div class="d">{top_html}</div></div>'
                     f'<div class="sig-bx c"><h4 class="c">🔀 交叉窗口</h4><div class="d">{cross_desc}</div></div>'
                     f'<div class="sig-bx f"><h4 class="f">🌱 发酵信号 <span style="padding:1px 6px;border-radius:8px;font-size:10px;{sc(ferm_sc)}">{ferm_sc}项</span></h4><div class="d">{ferm_html}</div></div>'
                     f'</div></div>')
    H.append('</div>')  # ch

    # ════════ 第三章:切换全景 ════════
    H.append(f'<div class="ch"><h2>第三章 · 全年切换全景</h2>')
    # 接力时间轴
    H.append('<h3>🗓️ 主线接力时间轴(金=长期 蓝=中期)</h3><div class="relay">')
    by_ind = defaultdict(list)
    for _, m in ml.iterrows():
        by_ind[m["行业"]].append(m)
    for ind in sorted(ml_inds):
        H.append(f'<div class="relay-row"><div class="bar-name" style="width:70px;text-align:right;padding-right:8px;color:var(--t2);">{ind}</div><div class="relay-track">')
        for m in by_ind[ind]:
            sw_ = int(m["开始周"]); ew = int(m["结束周"])
            lvl = m["级别"]; col = _LEVEL_COLORS.get(lvl, "#888")
            ret_v = float(m["累计涨幅"])
            left = (sw_ - weeks[0]) / max(len(weeks), 1) * 100
            width = max((ew - sw_ + 1) / max(len(weeks), 1) * 100, 2)
            H.append(f'<div class="relay-bar" style="left:{left:.1f}%;width:{width:.1f}%;background:{col};" title="{ind} {lvl} 第{sw_}-{ew}周 +{ret_v:.1f}%">{ret_v:+.0f}%</div>')
        H.append('</div></div>')
    H.append('</div>')
    # 切换矩阵总表
    H.append('<h3>📋 切换矩阵总表</h3><table class="mtx"><thead><tr>'
             '<th>序</th><th>切换周</th><th>旧主线</th><th>级别</th><th>→</th>'
             '<th>新主线</th><th>级别</th><th>见顶信号</th><th>交叉窗口</th><th>发酵信号</th><th>类型</th></tr></thead><tbody>')
    for i, s in sw.iterrows():
        og = _SECTOR_GROUP.get(s.get("旧主线", ""), "其他"); ng = _SECTOR_GROUP.get(s.get("新主线", ""), "其他")
        olc = "b-long" if s.get("旧_级别") == "长期主线" else "b-mid"
        nlc = "b-long" if s.get("新_级别") == "长期主线" else "b-mid"
        H.append(f'<tr><td>{i+1}</td><td>第{int(s["切换周"])}周</td><td>{s["旧主线"]}</td>'
                 f'<td><span class="badge {olc}">{s.get("旧_级别","")}</span></td><td style="color:var(--gold);">→</td>'
                 f'<td>{s["新主线"]}</td><td><span class="badge {nlc}">{s.get("新_级别","")}</span></td>'
                 f'<td>{"🟢" if s.get("旧_见顶信号强度",0)>=2 else "⚪"}{int(s.get("旧_见顶信号强度",0))}项</td>'
                 f'<td>{int(s.get("交叉窗口周数",0))}周</td>'
                 f'<td>{"🟢" if s.get("新_发酵信号强度",0)>=2 else "⚪"}{int(s.get("新_发酵信号强度",0))}项</td>'
                 f'<td>{og}→{ng}</td></tr>')
    H.append('</tbody></table></div>')

    # ════════ 第四章:纵向对比 ════════
    H.append(f'<div class="ch"><h2>第四章 · 纵向对比</h2>')
    ml_all = pd.read_csv(os.path.join(RAW_DIR, "2016_2025_mainlines_v3.csv"))
    ml_all = ml_all[ml_all["级别"].isin(["中期主线", "长期主线"])]
    # 动态取当年累计涨幅 TOP3 主线行业,看其在其他年份的表现
    yr_focus = ml[(ml["年份"] == year)].sort_values("累计涨幅", ascending=False)
    focus = yr_focus["行业"].head(3).tolist()
    if not focus:
        focus = ml[ml["年份"] == year]["行业"].head(3).tolist()
    focus_str = "、".join(focus)
    H.append(f'<h3>📊 {year}年核心主线行业({focus_str})在其他年份的表现</h3><table class="mtx"><thead><tr><th>行业</th>')
    for y in range(2016, 2026):
        H.append(f'<th>{y}</th>')
    H.append('</tr></thead><tbody>')
    for ind in focus:
        H.append(f'<tr><td style="text-align:left;font-weight:600;color:var(--gold);">{ind}</td>')
        for y in range(2016, 2026):
            rec = ml_all[(ml_all["行业"] == ind) & (ml_all["年份"] == y)]
            if rec.empty:
                H.append('<td style="color:var(--t3);">—</td>')
            else:
                best_ret = rec["累计涨幅"].max()
                lv = rec.loc[rec["累计涨幅"].idxmax(), "级别"]
                col = _LEVEL_COLORS.get(lv, "#888")
                rs = f"+{best_ret:.0f}%" if best_ret >= 0 else f"{best_ret:.0f}%"
                hl = ' style="background:rgba(241,196,15,0.1);"' if y == year else ""
                H.append(f'<td{hl}><span class="badge" style="background:rgba({_hex(col)},0.2);color:{col};">{rs}</span></td>')
        H.append('</tr>')
    H.append('</tbody></table>')
    # 相似切换模式:2023 vs 2019/2021
    H.append('<h3>🔄 跨年相似切换模式</h3>')
    sw_all = pd.read_csv(os.path.join(RAW_DIR, "2016_2025_switch_signals.csv"))
    for cmp_year in [2019, 2021]:
        H.append(f'<div class="note"><strong>{year} vs {cmp_year}:</strong></div><table class="mtx"><thead><tr>'
                 f'<th>{year}切换</th><th>见顶</th><th>发酵</th><th>类型</th>'
                 f'<th>vs</th><th>{cmp_year}切换</th><th>见顶</th><th>发酵</th><th>类型</th></tr></thead><tbody>')
        y1 = sw[sw["切换类型"].isin(sw_all[sw_all["年份"] == cmp_year]["切换类型"])] if not sw_all.empty else pd.DataFrame()
        y2 = sw_all[(sw_all["年份"] == cmp_year) & (sw_all["切换类型"].isin(sw["切换类型"]))] if not sw.empty else pd.DataFrame()
        rows_pairs = min(len(y1), len(y2), 5)
        for i in range(rows_pairs):
            a = y1.iloc[i]; b = y2.iloc[i]
            H.append(f'<tr><td>{a["旧主线"]}→{a["新主线"]}</td><td>{int(a.get("旧_见顶信号强度",0))}</td><td>{int(a.get("新_发酵信号强度",0))}</td><td>{a["切换类型"]}</td>'
                     f'<td style="color:var(--gold);">⟷</td>'
                     f'<td>{b["旧主线"]}→{b["新主线"]}</td><td>{int(b.get("旧_见顶信号强度",0))}</td><td>{int(b.get("新_发酵信号强度",0))}</td><td>{b["切换类型"]}</td></tr>')
        H.append('</tbody></table>')
    H.append('</div>')

    H.append(f'<div class="ft">{year}主线深度叙事 · 容间断滑窗算法v3 · 数据源:申万31行业日线</div></div></body></html>')

    out = os.path.join(REPORT_DIR, f"{year}_deep_narrative.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(H))
    print(f"\n{'='*60}\n  {year}年深度叙事报告完成\n  HTML: {out} ({os.path.getsize(out)/1024:.0f}KB)\n{'='*60}")
    return out


if __name__ == "__main__":
    import sys
    y = int(sys.argv[1]) if len(sys.argv) > 1 else 2023
    generate_deep_narrative(y)
