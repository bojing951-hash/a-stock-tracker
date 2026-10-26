# -*- coding: utf-8 -*-
"""
22行业产能周期投资综合仪表盘 (阶段4)
================================================
汇聚: 周期状态 + 回测绩效 + 实时指标 + 预警信号
输出: 终端彩色表格 + HTML 看板 (内嵌回测图表)

数据源:
  - raw_data/industry_cycle.csv         当前阶段/deviation
  - backtest_results/cycle_timing_summary.csv  回测绩效
  - dashboard/indicator_registry.py     strategy_override + 转换规则
  - dashboard/alert_engine.py           预警(转换/领先信号)
  - raw_data/index_daily/{行业}.csv     技术指标
  - raw_data/indicators/*.csv           核心指标最新值
"""
import os
import sys
import json
import base64
from datetime import datetime
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "dashboard"))

from indicator_registry import INDICATOR_REGISTRY
from alert_engine import AlertEngine

# ---------- ANSI 颜色 ----------
C_RED = "\033[91m"; C_GREEN = "\033[92m"; C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"; C_CYAN = "\033[96m"; C_BOLD = "\033[1m"
C_DIM = "\033[2m"; C_RESET = "\033[0m"


def _norm_date(v):
    v = str(v).strip()
    if "至今" in v or v in ("nan", ""):
        return "2026-06-21"
    if len(v) == 7:
        return f"{v}-01"
    return v


class CycleDashboard:
    def __init__(self, base_dir=BASE_DIR):
        self.base_dir = base_dir
        self.raw = os.path.join(base_dir, "raw_data")
        self.bt = os.path.join(base_dir, "backtest", "backtest_results")
        self.cycles = None
        self.backtest = None
        self.phases = None
        self.deviations = None
        self.alert_results = None
        self.latest_indicators = {}
        self.rows = []

    # ---------- 数据加载 ----------
    def load_all(self):
        self._load_cycles()
        self._load_backtest()
        self._load_alerts()
        self._load_indicators()
        self._build_rows()
        return self

    def _load_cycles(self):
        df = pd.read_csv(os.path.join(self.raw, "industry_cycle.csv"))
        df["_s"] = pd.to_datetime(df["起始日期"].astype(str).apply(_norm_date), errors="coerce")
        latest = df.sort_values("_s").groupby("行业名称").last().reset_index()
        self.cycles = {str(r["行业名称"]): {
            "phase": str(r["周期阶段_标准化"]),
            "start": str(r["起始日期"]),
            "end": str(r["结束日期"]),
            "deviation": "" if pd.isna(r.get("deviation_type")) else str(r["deviation_type"]),
            "all_segs": df[df["行业名称"].astype(str) == str(r["行业名称"])],
        } for _, r in latest.iterrows()}

    def _load_backtest(self):
        p = os.path.join(self.bt, "cycle_timing_summary.csv")
        self.backtest = pd.read_csv(p).set_index("行业名称") if os.path.exists(p) else pd.DataFrame()
        for f in ["phase_effectiveness.csv", "deviation_analysis.csv"]:
            pp = os.path.join(self.bt, f)
            if os.path.exists(pp):
                setattr(self, f.split("_")[0], pd.read_csv(pp))

    def _load_alerts(self):
        eng = AlertEngine()
        self.alert_results = eng.run_full_check()
        self._eng = eng

    def _load_indicators(self):
        """读取各指标CSV最新值"""
        ind_dir = os.path.join(self.raw, "indicators")
        self.latest_indicators = {}
        # 估值快照
        vp = os.path.join(ind_dir, "sw_valuation.csv")
        if os.path.exists(vp):
            v = pd.read_csv(vp)
            self.latest_indicators["_val"] = {str(r["industry"]): r for _, r in v.iterrows()}
        # 时序指标最新值
        for name in ["lithium_carbonate_futures", "gold_price_sge", "margin_balance",
                     "rebar_spot", "hog_price"]:
            p = os.path.join(ind_dir, f"{name}.csv")
            if not os.path.exists(p):
                continue
            df = pd.read_csv(p)
            self.latest_indicators[name] = {
                "last_date": str(df.iloc[-1, 0]) if len(df) else "",
                "rows": len(df),
            }

    def _industry_indicator_str(self, industry):
        """该行业核心指标最新值的紧凑字符串"""
        cfg = INDICATOR_REGISTRY.get(industry, {})
        parts = []
        val = self.latest_indicators.get("_val", {})
        for ind in cfg.get("indicators", []):
            if ind["source"] == "manual":
                continue
            if ind["source"] == "sw_valuation":
                row = val.get(ind.get("sw_industry"))
                if row is not None and ind.get("field") in row:
                    parts.append(f"{ind.get('sw_industry','')}PE={row[ind['field']]:.0f}")
            else:
                # 时序指标最新值(从alert_engine复用)
                v, _ = self._eng._get_latest_indicator(ind)
                if v is not None:
                    nm = ind["name"].replace("期货价", "").replace("基准价", "")
                    parts.append(f"{nm}={v:.0f}" if v > 100 else f"{nm}={v:.1f}")
        return "; ".join(parts[:2]) if parts else "-"

    def _calc_technicals(self, industry):
        return self._eng._calc_index_technicals(industry)

    def _calc_phase_duration(self, start_date):
        try:
            s = pd.to_datetime(_norm_date(start_date))
            return (datetime(2026, 6, 21) - s.to_pydatetime()).days
        except Exception:
            return 0

    # ---------- 推荐操作 ----------
    def _get_recommended_action(self, industry):
        cyc = self.cycles.get(industry, {})
        phase = cyc.get("phase", "")
        cfg = INDICATOR_REGISTRY.get(industry, {})
        override = cfg.get("strategy_override")
        # 找该行业预警
        ar = next((r for r in self.alert_results if r["行业"] == industry), None)
        triggered = ar["转换触发"] if ar else []
        is_bottom = ar["领先信号"]["is_bottom_candidate"] if ar else False

        # 1. 🔴转换触发
        for t in triggered:
            to_phase = t.split("→")[1]
            if to_phase == "景气顶部":
                return "⚠️考虑止盈", C_YELLOW
            if to_phase == "过剩期":
                return "⚠️建议减仓", C_YELLOW
            if to_phase == "出清期":
                return "⚠️减仓观望", C_YELLOW
            if to_phase in ("复苏期", "成长期"):
                return "⚠️准备建仓", C_CYAN
            if to_phase == "成熟稳定期":
                return "持有(转稳)", C_BLUE
        # 2. 🟡见底信号
        if is_bottom:
            return "⚠️可能见底", C_CYAN
        # 3. CONSERVATIVE_ONLY: 出清/过剩也持有
        if override == "CONSERVATIVE_ONLY":
            if phase in ("出清期", "过剩期"):
                return "保守持有", C_BLUE
            return "持有(保守)", C_BLUE
        # 4. 按binary阶段仓位
        if phase in ("成长期", "复苏期"):
            return "满仓持有", C_GREEN
        if phase == "景气顶部":
            return "减仓至50%", C_YELLOW
        if phase == "成熟稳定期":
            return "持有75%", C_BLUE
        if phase in ("过剩期", "出清期"):
            return "空仓观望", C_DIM
        return "持有", C_BLUE

    # ---------- 行汇总 ----------
    def _build_rows(self):
        self.rows = []
        for ind in INDICATOR_REGISTRY:
            cyc = self.cycles.get(ind, {})
            bt = self.backtest.loc[ind] if ind in self.backtest.index else None
            ar = next((r for r in self.alert_results if r["行业"] == ind), {})
            action, color = self._get_recommended_action(ind)
            excess = bt["binary_超额年化"] if bt is not None and "binary_超额年化" in bt.index else None
            triggered = ar.get("转换触发", [])
            lvl = "转换" if triggered else ("见底" if ar.get("领先信号", {}).get("is_bottom_candidate") else "正常")
            warn = ""
            if triggered:
                t = triggered[0]
                warn = f"🔴{t}"
            elif ar.get("领先信号", {}).get("is_bottom_candidate"):
                warn = "🟡见底候选"
            self.rows.append({
                "行业": ind, "phase": cyc.get("phase", "?"),
                "days": self._calc_phase_duration(cyc.get("start", "")),
                "excess": excess, "indicators": self._industry_indicator_str(ind),
                "action": action, "color": color, "level": lvl, "warn": warn,
                "override": INDICATOR_REGISTRY[ind].get("strategy_override", ""),
                "deviation": cyc.get("deviation", ""),
            })

    # ---------- 终端输出 ----------
    def print_terminal(self):
        today = datetime.now().strftime("%Y-%m-%d")
        W = 110
        print(C_BOLD + "╔" + "═" * W + "╗" + C_RESET)
        title = f"产能周期投资系统 — 22行业仪表盘  ({today})"
        print(C_BOLD + "║" + title.center(W) + "║" + C_RESET)
        print(C_BOLD + "╚" + "═" * W + "╝" + C_RESET)
        print()

        red = [r for r in self.rows if r["level"] == "转换"]
        yellow = [r for r in self.rows if r["level"] == "见底"]
        normal = [r for r in self.rows if r["level"] == "正常"]

        # 预警行业
        aw = red + yellow
        print(C_RED + C_BOLD + f"{'🔴/🟡 预警行业（需关注）':<20}".ljust(W) + C_RESET)
        if aw:
            print(f"{'行业':<10}{'当前阶段':<10}{'持续':>6}{'超额%':>8}  {'核心指标':<24}{'预警信号'}")
            print("-" * 100)
            for r in aw:
                ex = f"{r['excess']:+.1f}" if r['excess'] is not None else "  -"
                print(f"{r['行业']:<10}{r['phase']:<10}{r['days']:>4}天{ex:>8}  {r['indicators'][:24]:<24}{C_RED}{r['warn']}{C_RESET}")
        else:
            print("  (无)")
        print()

        # 正常行业按操作分组
        print(C_GREEN + C_BOLD + "✅ 正常行业（按推荐操作分组）" + C_RESET)
        order = ["满仓持有", "持有75%", "持有(保守)", "保守持有", "持有(转稳)",
                 "减仓至50%", "⚠️考虑止盈", "⚠️建议减仓", "⚠️减仓观望", "空仓观望"]
        groups = {}
        for r in normal:
            groups.setdefault(r["action"], []).append(r)
        print(f"{'行业':<10}{'当前阶段':<10}{'持续':>6}{'超额%':>8}  {'核心指标':<24}{'推荐操作':<14}{'备注'}")
        print("-" * 100)
        for act in order:
            if act not in groups:
                continue
            grp = sorted(groups[act], key=lambda x: -(x["excess"] or 0))
            tag = "【保守模式】" if any(g["override"] == "CONSERVATIVE_ONLY" for g in grp) else ""
            print(f"{C_BOLD}{act} {tag}{C_RESET}".ljust(40))
            for r in grp:
                ex = f"{r['excess']:+.1f}" if r['excess'] is not None else "  -"
                note = r["deviation"] if r["deviation"] else ""
                color = r["color"]
                print(f"  {r['行业']:<8}{r['phase']:<10}{r['days']:>4}天{ex:>8}  "
                      f"{r['indicators'][:24]:<24}{color}{act:<12}{C_RESET}{note}")
        print()

        # 回测绩效摘要
        self._print_backtest_summary()
        # 数据状态
        self._print_data_status()

    def _print_backtest_summary(self):
        print(C_CYAN + C_BOLD + "📊 回测绩效摘要" + C_RESET)
        if len(self.backtest):
            b = self.backtest
            mean_all = b["binary_超额年化"].mean()
            mean_a = b[b["数据组别"] == "A"]["binary_超额年化"].mean() if "数据组别" in b.columns else 0
            mean_b = b[b["数据组别"] == "B"]["binary_超额年化"].mean() if "数据组别" in b.columns else 0
            pos = (b["binary_超额年化"] > 0).sum()
            print(f"  全行业binary平均超额: {mean_all:+.2f}% | A组: {mean_a:+.1f}% | B组: {mean_b:+.1f}%")
            print(f"  正超额行业: {pos}/{len(b)} ({pos/len(b)*100:.0f}%)")
        if self.phases is not None:
            best = self.phases.loc[self.phases["平均基准年化%"].idxmin()] if len(self.phases) else None
            print(f"  最有效择时阶段: 过剩期(空仓规避下跌, 基准仅4.3%正收益)")
        if self.deviation is not None and len(self.deviation):
            worst = self.deviation.iloc[0]
            print(f"  最危险偏离: {worst['deviation_type']}(误判率{worst['策略误判率%']:.0f}%, 超额损失{worst['平均超额损失%']:+.1f}%)")
        print()

    def _print_data_status(self):
        print(C_CYAN + C_BOLD + "📋 数据更新状态" + C_RESET)
        # 指数最新日期
        idx_dir = os.path.join(self.raw, "index_daily")
        idx_dates = []
        for f in os.listdir(idx_dir):
            if f.endswith(".csv"):
                try:
                    d = pd.read_csv(os.path.join(idx_dir, f), usecols=[0])
                    idx_dates.append(str(d.iloc[-1, 0]))
                except Exception:
                    pass
        idx_latest = max(idx_dates) if idx_dates else "?"
        print(f"  指数日线最新: {idx_latest}")
        for name, info in self.latest_indicators.items():
            if name == "_val":
                continue
            print(f"  {name}: 最新 {info['last_date']} ({info['rows']}行)")
        alerts_csv = os.path.join(self.raw, "alerts", "alerts_log.csv")
        if os.path.exists(alerts_csv):
            n = len(pd.read_csv(alerts_csv))
            print(f"  预警日志: {alerts_csv} ({n}条记录)")
        print()

    # ---------- HTML 输出 ----------
    def generate_html(self):
        charts_dir = self.bt
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        # 计算汇总
        b = self.backtest
        mean_all = b["binary_超额年化"].mean() if len(b) else 0
        pos = (b["binary_超额年化"] > 0).sum() if len(b) else 0

        def b64img(fname):
            p = os.path.join(charts_dir, fname)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            return None

        html = [f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>产能周期投资仪表盘</title>
<style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;max-width:1200px;margin:auto;padding:20px;background:#f8f9fa;color:#222}}
h1{{color:#1a3a5c;border-bottom:3px solid #1a3a5c;padding-bottom:8px}}
h2{{color:#1a3a5c;margin-top:30px}}
table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1);font-size:13px}}
th{{background:#1a3a5c;color:#fff;padding:8px;text-align:left;position:sticky;top:0}}
td{{padding:6px 8px;border-bottom:1px solid #eee}}
tr:hover{{background:#eef5fb}}
.red{{background:#ffe5e5}} .yellow{{background:#fff8e1}}
.pos{{color:#1a7f37;font-weight:bold}} .neg{{color:#cf222e;font-weight:bold}}
.tag{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;color:#fff}}
.t-满仓{{background:#1a7f37}} .t-持有{{background:#0969da}} .t-空仓{{background:#6e7781}}
.t-减仓{{background:#d29922}} .t-止盈{{background:#bf3989}} .t-保守{{background:#6f42c1}}
.t-建仓{{background:#1f883d}} .t-见底{{background:#0a8a5f}}
.kpi{{display:inline-block;background:#fff;padding:12px 18px;margin:6px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1);min-width:140px}}
.kpi b{{display:block;font-size:22px;color:#1a3a5c}}
.det{{display:none;margin-top:10px;padding:12px;background:#fff;border-left:3px solid #0969da;border-radius:4px}}
.det.show{{display:block}}
a.ind{{color:#0969da;cursor:pointer;text-decoration:underline}}
</style></head><body>
<h1>🏭 产能周期投资系统 — 22行业仪表盘</h1>
<p style="color:#666">更新时间: {today} | 数据基准日: 2026-06-18</p>
<div>
<div class="kpi"><b>{mean_all:+.2f}%</b>全行业平均超额(binary)</div>
<div class="kpi"><b>{pos}/{len(b)}</b>正超额行业</div>
<div class="kpi"><b>{sum(1 for r in self.rows if r['level']!='正常')}</b>预警行业</div>
<div class="kpi"><b>{sum(1 for r in self.rows if r['override']=='CONSERVATIVE_ONLY')}</b>保守模式行业</div>
</div>
"""]

        # 主表
        html.append("<h2>📊 22行业综合看板</h2>")
        html.append("<table><tr><th>行业</th><th>当前阶段</th><th>持续天数</th><th>binary超额</th>"
                    "<th>策略年化</th><th>基准年化</th><th>夏普</th><th>核心指标</th>"
                    "<th>推荐操作</th><th>预警</th></tr>")
        # 排序: 预警优先 -> 超额降序
        sorted_rows = sorted(self.rows, key=lambda r: (0 if r["level"] != "正常" else 1, -(r["excess"] or 0)))
        for r in sorted_rows:
            cls = "red" if r["level"] == "转换" else ("yellow" if r["level"] == "见底" else "")
            bt = self.backtest.loc[r["行业"]] if r["行业"] in self.backtest.index else None
            ex = r["excess"]
            ex_cls = "pos" if (ex is not None and ex >= 0) else "neg"
            ex_str = f"{ex:+.1f}%" if ex is not None else "-"
            sa = f"{bt['binary_年化收益']:+.1f}%" if bt is not None else "-"
            ba = f"{bt['binary_基准年化']:+.1f}%" if bt is not None else "-"
            sh = f"{bt['binary_夏普']:.2f}" if bt is not None else "-"
            act = r["action"]
            act_tag = ("t-满仓" if "满仓" in act else "t-空仓" if "空仓" in act else
                       "t-减仓" if "减仓" in act else "t-止盈" if "止盈" in act else
                       "t-建仓" if "建仓" in act else "t-见底" if "见底" in act else "t-保守"
                       if "保守" in act or "持有" in act else "t-持有")
            warn = r["warn"] if r["warn"] else ("🟢" if r["level"] == "正常" else "")
            html.append(
                f"<tr class='{cls}' id='row-{r['行业']}'>"
                f"<td><a class='ind' onclick=\"toggle('{r['行业']}')\">{r['行业']}</a></td>"
                f"<td>{r['phase']}</td><td>{r['days']}天</td>"
                f"<td class='{ex_cls}'>{ex_str}</td><td>{sa}</td><td>{ba}</td><td>{sh}</td>"
                f"<td style='font-size:11px'>{r['indicators']}</td>"
                f"<td><span class='tag {act_tag}'>{act}</span></td>"
                f"<td style='font-size:11px'>{warn}</td></tr>")
            # 详情行
            html.append(self._detail_html(r["行业"]))
        html.append("</table>")

        # 图表
        for fname, cap in [("chart_1_excess_return.png", "图1: 22行业超额收益(binary)"),
                           ("chart_2_phase_effectiveness.png", "图2: 周期阶段效果验证")]:
            img = b64img(fname)
            if img:
                html.append(f"<h2>{cap}</h2><img src='data:image/png;base64,{img}' style='width:100%;max-width:900px'>")
        # 阶段有效性 + deviation 表
        if self.phases is not None:
            html.append("<h2>🧪 周期阶段效果验证</h2><table><tr><th>阶段</th><th>平均基准年化</th>"
                        "<th>正收益占比</th><th>样本段数</th></tr>")
            for _, r in self.phases.iterrows():
                html.append(f"<tr><td>{r['phase']}</td><td class='{'pos' if r['平均基准年化%']>0 else 'neg'}'>"
                            f"{r['平均基准年化%']:+.2f}%</td><td>{r['正收益占比%']:.0f}%</td>"
                            f"<td>{r['样本段数']:.0f}</td></tr>")
            html.append("</table>")
        if self.deviation is not None:
            html.append("<h2>⚠️ deviation_type 影响分析</h2><table><tr><th>偏离类型</th><th>段数</th>"
                        "<th>误判率</th><th>平均超额损失</th></tr>")
            for _, r in self.deviation.iterrows():
                html.append(f"<tr><td>{r['deviation_type']}</td><td>{r['段数']:.0f}</td>"
                            f"<td>{r['策略误判率%']:.0f}%</td>"
                            f"<td class='{'neg' if r['平均超额损失%']>0 else 'pos'}'>{r['平均超额损失%']:+.2f}%</td></tr>")
            html.append("</table>")

        html.append("<script>function toggle(n){var e=document.getElementById('det-'+n);"
                    "e.classList.toggle('show');}</script></body></html>")
        out = os.path.join(BASE_DIR, "dashboard", "cycle_dashboard.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(html))
        return out

    def _detail_html(self, industry):
        """单行业详情(周期段+三模式+规则+预警日志)"""
        cyc = self.cycles.get(industry, {})
        segs = cyc.get("all_segs")
        bt = self.backtest.loc[industry] if industry in self.backtest.index else None
        cfg = INDICATOR_REGISTRY.get(industry, {})
        h = [f"<tr class='det' id='det-{industry}'><td colspan='10'>"]
        # 三模式
        if bt is not None:
            h.append(f"<b>三模式绩效</b>: binary年化{bt['binary_年化收益']:+.1f}%/"
                     f"aggressive{bt.get('aggressive_年化收益','?')}%/"
                     f"conservative{bt.get('conservative_年化收益','?')}% | "
                     f"夏普{bt['binary_夏普']:.2f} | 回撤{bt['binary_最大回撤']:.1f}%<br>")
        # 转换规则
        rules = cfg.get("transition_rules", {})
        h.append("<b>转换规则</b>: " + "; ".join(f"{k}←{v}" for k, v in rules.items()) + "<br>")
        # 周期段
        if segs is not None and len(segs):
            h.append("<b>周期段</b>: ")
            h.append("; ".join(f"{r['起始日期']}~{r['结束日期']}[{r['周期阶段_标准化']}]"
                               for _, r in segs.iterrows()))
        # 预警日志最近5条
        alerts_csv = os.path.join(self.raw, "alerts", "alerts_log.csv")
        if os.path.exists(alerts_csv):
            al = pd.read_csv(alerts_csv)
            al = al[al["行业"].astype(str) == industry].tail(5)
            if len(al):
                h.append("<br><b>最近预警</b>: " + " | ".join(
                    f"{r['日期']}[{r['预警级别']}]" for _, r in al.iterrows()))
        h.append("</td></tr>")
        return "".join(h)


if __name__ == "__main__":
    db = CycleDashboard()
    db.load_all()
    db.print_terminal()
    # 2026-10-03修复: 此前main只打印终端摘要,从未调用generate_html,
    # 导致 cycle_dashboard.html 自6/21起停更(每周只有日志里的文字版)
    try:
        out = db.generate_html()
        print(f"\n[OK] HTML看板已更新: {out}")
    except Exception as e:
        print(f"[警告] HTML看板生成失败: {repr(e)[:120]}")
