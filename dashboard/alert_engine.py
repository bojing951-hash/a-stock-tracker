# -*- coding: utf-8 -*-
"""
预警引擎 (阶段3/核心)
================================================
职责:
  1. 读取每个行业当前周期阶段 + 最新指标值 + 指数技术指标
  2. 评估 transition_rules 是否触发阶段转换
  3. 评估 leading_signals (出清/过剩期见底领先信号) —— 解决回测"出清期踏空"
  4. 输出 3 类结果: 🔴转换 / 🟡领先信号 / 🟢正常，并追加 alerts_log.csv

规则语法 (transition_rules 的值):
  多个子条件用 AND 连接。子条件类型:
    数值:   "碳酸锂期货价 > 100000"   / "煤炭行业PE_TTM > 15"
    区间:   "上海金基准价 在 800-950"
    技术面: "指数突破60日均线" / "指数跌破60日均线" / "指数突破120日均线"
            "指数突破250日均线" / "指数创250日新低" / "指数60日涨幅 > 40%"
            "RSI_14 > 80"
    持续:   "碳酸锂期货价 > 100000 持续20日"   (近N日全部满足)
    回落:   "碳酸锂期货价 从峰值回落 > 30%"     (从区间内最高点回落)
            "两融余额 从峰值回落 > 15%"
    人工:   含 "企稳/转正/放缓/增长/同比/环比" 等定性词 -> pending_manual
"""
import os
import re
import sys
import json
from datetime import datetime
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "dashboard"))
from indicator_registry import INDICATOR_REGISTRY

CYCLE_CSV = os.path.join(BASE_DIR, "raw_data", "industry_cycle.csv")
INDEX_DIR = os.path.join(BASE_DIR, "raw_data", "index_daily")
IND_DIR = os.path.join(BASE_DIR, "raw_data", "indicators")
ALERTS_CSV = os.path.join(BASE_DIR, "raw_data", "alerts", "alerts_log.csv")

# 定性词 -> 人工确认
MANUAL_KEYWORDS = ["企稳", "转正", "放缓", "增长", "同比", "环比", "合同负债",
                   "产能利用率", "装机量", "招标量", "销售额", "销售面积",
                   "批价", "出货量", "渗透率", "政策", "集采", "版号"]

SOURCE_FILES = {
    "sw_valuation": "sw_valuation.csv",
    "margin": "margin_balance.csv",
    "gold_sge": "gold_price_sge.csv",
    "lithium": "lithium_carbonate_futures.csv",
    "rebar": "rebar_spot.csv",
}


def _norm_date(v):
    v = str(v).strip()
    if "至今" in v or v in ("nan", ""):
        return "2026-06-21"
    if len(v) == 7:
        return f"{v}-01"
    return v


class AlertEngine:
    def __init__(self, registry=INDICATOR_REGISTRY, cycle_csv=CYCLE_CSV,
                 index_dir=INDEX_DIR, indicator_dir=IND_DIR):
        self.registry = registry
        self.cycle_csv = cycle_csv
        self.index_dir = index_dir
        self.indicator_dir = indicator_dir
        self.cycles = self._load_current_phases()
        self._val_cache = None
        self._tech_cache = {}

    # ---------- 当前阶段 ----------
    def _load_current_phases(self):
        df = pd.read_csv(self.cycle_csv)
        df["_s"] = pd.to_datetime(df["起始日期"].astype(str).apply(_norm_date), errors="coerce")
        latest = (df.sort_values("_s").groupby("行业名称").last().reset_index())
        out = {}
        for _, r in latest.iterrows():
            out[str(r["行业名称"])] = {
                "phase": str(r["周期阶段_标准化"]),
                "start": str(r["起始日期"]),
                "end": str(r["结束日期"]),
            }
        return out

    # ---------- 指标值 ----------
    def _load_valuation(self):
        if self._val_cache is None:
            v = pd.read_csv(os.path.join(self.indicator_dir, "sw_valuation.csv"))
            self._val_cache = {str(r["industry"]): r for _, r in v.iterrows()}
        return self._val_cache

    def _get_latest_indicator(self, cfg):
        """返回 (latest_value, series_df) 或 (None, None) for manual。"""
        src = cfg.get("source")
        if src == "manual":
            return None, None
        fname = SOURCE_FILES.get(src)
        if not fname or not os.path.exists(os.path.join(self.indicator_dir, fname)):
            return None, None
        df = pd.read_csv(os.path.join(self.indicator_dir, fname))
        field = cfg.get("field")
        if src == "sw_valuation":
            row = self._load_valuation().get(cfg.get("sw_industry"))
            if row is None or field not in row:
                return None, None
            return float(row[field]), None
        # 时序指标
        datecol = "date" if "date" in df.columns else df.columns[0]
        df = df.sort_values(datecol)
        if field not in df.columns:
            return None, None
        df = df[[datecol, field]].rename(columns={field: "val"}).dropna()
        if df.empty:
            return None, None
        return float(df["val"].iloc[-1]), df

    def _industry_indicators(self, industry):
        """返回 {指标名: latest_value} 字典"""
        out = {}
        for cfg in self.registry[industry]["indicators"]:
            val, _ = self._get_latest_indicator(cfg)
            out[cfg["name"]] = val
        return out

    # ---------- 技术指标 ----------
    def _calc_index_technicals(self, industry):
        if industry in self._tech_cache:
            return self._tech_cache[industry]
        path = os.path.join(self.index_dir, f"{industry}.csv")
        t = {"available": False}
        if not os.path.exists(path):
            self._tech_cache[industry] = t
            return t
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        c = df["close"].astype(float)
        v = df["volume"].astype(float)
        if len(df) < 60:
            self._tech_cache[industry] = t
            return t
        ma60 = c.rolling(60).mean()
        ma120 = c.rolling(120).mean()
        ma250 = c.rolling(250).mean()
        vol_ma20 = v.rolling(20).mean()
        vol_ma60 = v.rolling(60).mean()
        # RSI14
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        last = c.iloc[-1]
        ret_60d = (last / c.iloc[-61] - 1) * 100 if len(c) > 60 else np.nan
        ret_20d = (last / c.iloc[-21] - 1) * 100 if len(c) > 20 else np.nan
        high_250 = c.iloc[-250:].max() if len(c) >= 250 else c.max()
        low_250 = c.iloc[-250:].min() if len(c) >= 250 else c.min()
        # 峰值(近250日)及回落幅度
        recent = c.iloc[-250:] if len(c) >= 250 else c
        peak = recent.max()
        from_peak = (last / peak - 1) * 100  # 负值=回撤
        # 30日波动率(日收益std年化)
        vol30 = c.pct_change().iloc[-30:].std() * np.sqrt(252) * 100
        t = {
            "available": True,
            "price": last, "date": str(df["date"].iloc[-1].date()),
            "ma60": ma60.iloc[-1], "ma120": ma120.iloc[-1], "ma250": ma250.iloc[-1],
            "above_ma60": last > ma60.iloc[-1] if not np.isnan(ma60.iloc[-1]) else None,
            "above_ma120": last > ma120.iloc[-1] if not np.isnan(ma120.iloc[-1]) else None,
            "above_ma250": last > ma250.iloc[-1] if not np.isnan(ma250.iloc[-1]) else None,
            "rsi14": rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else None,
            "ret_60d": ret_60d, "ret_20d": ret_20d,
            "is_new_low_250": last <= low_250 * 1.001,
            "is_new_high_250": last >= high_250 * 0.999,
            "from_peak": from_peak, "vol30": vol30,
            "vol_ratio_20_60": vol_ma20.iloc[-1] / vol_ma60.iloc[-1]
                if not np.isnan(vol_ma60.iloc[-1]) and vol_ma60.iloc[-1] > 0 else None,
            "close_series": c, "date_series": df["date"],
        }
        self._tech_cache[industry] = t
        return t

    # ---------- 规则解析与评估 ----------
    @staticmethod
    def _split_conditions(rule):
        """按 AND 拆分（保留'从峰值回落'里的词）"""
        parts = [p.strip() for p in re.split(r"\s+AND\s+", rule)]
        return [p for p in parts if p]

    def _eval_one_condition(self, cond, ind_vals, tech, industry):
        """返回 ('met'|'unmet'|'pending_manual', detail)"""
        c = cond.strip()
        # 人工定性词
        if any(k in c for k in MANUAL_KEYWORDS) and not re.search(r"[<>]\s*\d", c):
            return "pending_manual", c
        # 含人工词 + 数值 -> 仍需人工(如"碳酸锂企稳 AND 装机量>30%")：本条标人工
        if any(k in c for k in MANUAL_KEYWORDS):
            return "pending_manual", c

        # 持续N日: "<指标名> <op> <num> 持续N日"
        m = re.match(r"^(.+?)\s*(>|<|>=|<=)\s*([\d.]+)\s*持续(\d+)日$", c)
        if m:
            name, op, num, days = m.group(1).strip(), m.group(2), float(m.group(3)), int(m.group(4))
            series = self._indicator_series(industry, name)
            if series is None or len(series) < days:
                return "unmet", f"{name}数据不足{days}日"
            tail = series.tail(days)
            vals = tail["val"].values
            ok = {"<": np.all(vals < num), ">": np.all(vals > num),
                  ">=": np.all(vals >= num), "<=": np.all(vals <= num)}[op]
            return ("met" if ok else "unmet"), f"{name}{op}{num} 持续{days}日({'满足' if ok else '未满足'})"

        # 回落: "<指标名> 从峰值回落 > X%"
        m = re.match(r"^(.+?)\s*从峰值回落\s*>\s*([\d.]+)%?$", c)
        if m:
            name, pct = m.group(1).strip(), float(m.group(2))
            if name.startswith("指数"):
                if not tech.get("available"):
                    return "unmet", "指数数据缺失"
                drop = -tech["from_peak"]  # 正值=回撤幅度
                ok = drop > pct
                return ("met" if ok else "unmet"), f"指数从峰值回撤{drop:.1f}% {'>' if ok else '<='}{pct}%"
            series = self._indicator_series(industry, name)
            if series is None or len(series) < 2:
                return "unmet", f"{name}数据不足"
            peak = series["val"].max(); last = series["val"].iloc[-1]
            drop = (peak - last) / peak * 100
            ok = drop > pct
            return ("met" if ok else "unmet"), f"{name}从峰值{peak:.0f}回落{drop:.1f}% {'>' if ok else '<='}{pct}%"

        # 区间: "<指标名> 在 <a>-<b>"  (可选 持续N日)
        m = re.match(r"^(.+?)\s*在\s*([\d.]+)-([\d.]+)\s*(持续(\d+)日)?$", c)
        if m:
            name, a, b = m.group(1).strip(), float(m.group(2)), float(m.group(3))
            days = int(m.group(5)) if m.group(5) else None
            val = ind_vals.get(name) if not name.startswith("指数") else None
            if val is None:
                return "unmet", f"{name}无值"
            ok_now = a <= val <= b
            if days:  # 需验持续性
                # PE估值是快照(无时序) -> 无法验持续，降级人工
                if name.endswith("PE_TTM"):
                    return "pending_manual", f"{name}当前{val:.1f}在[{a},{b}]，但需持续{days}日(PE为快照,需人工确认)"
                # 时序指标：检查近N日是否全部落在区间
                series = self._indicator_series(industry, name)
                if series is None or len(series) < days:
                    return "unmet", f"{name}数据不足{days}日"
                tail = series.tail(days)["val"].values
                ok = np.all((tail >= a) & (tail <= b))
                return ("met" if ok else "unmet"), f"{name}近{days}日{'全部' if ok else '未'}落在[{a},{b}](当前{val:.1f})"
            return ("met" if ok_now else "unmet"), f"{name}={val:.1f} {'在' if ok_now else '不在'}[{a},{b}]"

        # 技术面纯文本
        if c == "指数突破60日均线":
            ok = tech.get("above_ma60")
            return ("met" if ok else "unmet"), f"现价{'>' if ok else '<='}60日均线"
        if c == "指数跌破60日均线":
            ok = tech.get("available") and not tech.get("above_ma60")
            return ("met" if ok else "unmet"), f"现价{'<' if ok else '>='}60日均线"
        if c == "指数突破120日均线":
            ok = tech.get("above_ma120")
            return ("met" if ok else "unmet"), f"现价{'>' if ok else '<='}120日均线"
        if c == "指数突破250日均线":
            ok = tech.get("above_ma250")
            return ("met" if ok else "unmet"), f"现价{'>' if ok else '<='}250日均线"
        if c == "指数创250日新低":
            ok = tech.get("is_new_low_250")
            return ("met" if ok else "unmet"), f"{'创' if ok else '未创'}250日新低"
        if c.startswith("金价30日波动率") or c.startswith("指数30日波动率"):
            m2 = re.match(r".*波动率\s*>\s*([\d.]+)%?", c)
            if m2 and tech.get("vol30") is not None:
                pct = float(m2.group(1)); ok = tech["vol30"] > pct
                return ("met" if ok else "unmet"), f"30日波动率{tech['vol30']:.1f}% {'>' if ok else '<='}{pct}%"

        # RSI_14 > N
        m = re.match(r"^RSI_14\s*(>|<|>=|<=)\s*([\d.]+)$", c)
        if m:
            op, num = m.group(1), float(m.group(2))
            rsi = tech.get("rsi14")
            if rsi is None:
                return "unmet", "RSI数据不足"
            ok = {">": rsi > num, "<": rsi < num, ">=": rsi >= num, "<=": rsi <= num}[op]
            return ("met" if ok else "unmet"), f"RSI14={rsi:.1f} {op}{num}"

        # 指数60日涨幅 > X%
        m = re.match(r"^指数60日涨幅\s*(>|<|>=|<=)\s*([\d.]+)%?$", c)
        if m:
            op, num = m.group(1), float(m.group(2))
            r60 = tech.get("ret_60d")
            if r60 is None or np.isnan(r60):
                return "unmet", "60日涨幅数据不足"
            ok = {">": r60 > num, "<": r60 < num, ">=": r60 >= num, "<=": r60 <= num}[op]
            return ("met" if ok else "unmet"), f"60日涨幅{r60:.1f}% {op}{num}%"

        # 通用数值: "<指标名> <op> <num>"
        m = re.match(r"^(.+?)\s*(>|<|>=|<=)\s*([\d.]+)$", c)
        if m:
            name, op, num = m.group(1).strip(), m.group(2), float(m.group(3))
            val = ind_vals.get(name)
            if val is None:
                return "unmet", f"{name}无值"
            ok = {">": val > num, "<": val < num, ">=": val >= num, "<=": val <= num}[op]
            return ("met" if ok else "unmet"), f"{name}={val:.1f} {op}{num}({'满足' if ok else '未满足'})"

        # 动力煤期货跌破800 等无指标名数值 -> 标人工(无数据源)
        if any(k in c for k in ["动力煤", "MLCC", "费城", "硅料", "硅片", "组件",
                                 "成交量", "成交额", "DXY", "央行购金"]):
            return "pending_manual", c

        return "pending_manual", f"未识别规则: {c}"

    def _indicator_series(self, industry, name):
        """按指标名取时序(含date,val)"""
        for cfg in self.registry[industry]["indicators"]:
            if cfg["name"] == name:
                _, s = self._get_latest_indicator(cfg)
                return s
        return None

    # ---------- 转换评估 ----------
    def _evaluate_transitions(self, industry):
        cur_phase = self.cycles.get(industry, {}).get("phase", "未知")
        ind_vals = self._industry_indicators(industry)
        tech = self._calc_index_technicals(industry)
        rules = self.registry[industry].get("transition_rules", {})
        triggered = []
        evaluated = []
        for trans, rule in rules.items():
            from_phase = trans.split("→")[0]
            if from_phase != cur_phase:
                continue  # 只评估从当前阶段出发的规则
            conds = self._split_conditions(rule)
            sub = []
            all_met = True
            has_manual = False
            for cond in conds:
                status, detail = self._eval_one_condition(cond, ind_vals, tech, industry)
                sub.append({"cond": cond, "status": status, "detail": detail})
                if status == "unmet":
                    all_met = False
                if status == "pending_manual":
                    has_manual = True
                    all_met = False
            evaluated.append({"transition": trans, "conditions": sub,
                              "all_met": all_met, "has_manual": has_manual})
            if all_met:
                triggered.append(trans)
        return {"current_phase": cur_phase, "triggered": triggered,
                "evaluated": evaluated, "ind_vals": ind_vals, "tech_summary": self._tech_brief(tech)}

    @staticmethod
    def _tech_brief(tech):
        if not tech.get("available"):
            return "指数数据缺失"
        return (f"现价{tech['price']:.0f} MA60{'↑' if tech['above_ma60'] else '↓'} "
                f"RSI{tech['rsi14']:.0f} 60日{tech['ret_60d']:+.1f}% "
                f"量比20/60={tech['vol_ratio_20_60']:.2f}")

    # ---------- 领先信号(出清/过剩期见底预警) ----------
    def _evaluate_leading_signals(self, industry):
        """解决回测'出清期踏空': 在出清/过剩期检测见底领先信号"""
        cur = self.cycles.get(industry, {}).get("phase", "")
        tech = self._calc_index_technicals(industry)
        result = {"phase": cur, "is_bottom_candidate": False, "signals": [], "advice": ""}
        if cur not in ("出清期", "过剩期") or not tech.get("available"):
            return result
        score = 0
        # 1) 突破60日均线
        if tech.get("above_ma60"):
            result["signals"].append("✓ 指数站上60日均线"); score += 1
        else:
            result["signals"].append("✗ 未站上60日均线")
        # 2) 近20日涨幅>15%
        if tech.get("ret_20d") is not None and tech["ret_20d"] > 15:
            result["signals"].append(f"✓ 近20日涨幅{tech['ret_20d']:+.1f}%>15%(V型反弹)"); score += 1
        else:
            r = tech.get("ret_20d")
            result["signals"].append(f"✗ 近20日涨幅{r:+.1f}%≤15%" if r is not None else "✗ 20日涨幅数据不足")
        # 3) 放量: 20日均量>60日均量×1.3
        vr = tech.get("vol_ratio_20_60")
        if vr is not None and vr > 1.3:
            result["signals"].append(f"✓ 放量(20/60量比={vr:.2f}>1.3)"); score += 1
        else:
            result["signals"].append(f"✗ 未放量(量比={vr:.2f})" if vr is not None else "✗ 量能数据不足")
        result["is_bottom_candidate"] = score >= 2
        if score >= 2:
            result["advice"] = (f"⚠️ {industry}当前{cur}，但{score}/3见底信号已出现，"
                                f"建议准备转入复苏期(避免出清末期踏空，参考conservative模式持仓)")
        elif score == 1:
            result["advice"] = f"{industry}({cur})见底信号{score}/3，持续观察"
        else:
            result["advice"] = f"{industry}({cur})无见底信号，维持空仓判断"
        return result

    def _get_strategy_override(self, industry):
        return self.registry[industry].get("strategy_override", "BINARY")

    # ---------- 全量检查 ----------
    def run_full_check(self):
        results = []
        for industry in self.registry:
            tr = self._evaluate_transitions(industry)
            ld = self._evaluate_leading_signals(industry)
            results.append({
                "行业": industry,
                "当前阶段": tr["current_phase"],
                "转换触发": tr["triggered"],
                "转换评估": tr["evaluated"],
                "领先信号": ld,
                "核心指标": tr["ind_vals"],
                "技术摘要": tr["tech_summary"],
                "策略建议": self._get_strategy_override(industry),
                "检查时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
        return results

    # ---------- 报告 ----------
    def generate_alert_report(self, results):
        red, yellow, green = [], [], []
        for r in results:
            if r["转换触发"]:
                red.append(r)
            elif r["领先信号"]["is_bottom_candidate"]:
                yellow.append(r)
            else:
                green.append(r)
        return {"red": red, "yellow": yellow, "green": green}

    def append_alerts_log(self, results):
        os.makedirs(os.path.dirname(ALERTS_CSV), exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        for r in results:
            level = "转换" if r["转换触发"] else ("领先信号" if r["领先信号"]["is_bottom_candidate"] else "正常")
            trig = "; ".join(r["转换触发"]) if r["转换触发"] else ""
            vals = "; ".join(f"{k}={v:.1f}" for k, v in r["核心指标"].items() if v is not None)
            advice = r["领先信号"]["advice"]
            rows.append({"日期": today, "行业": r["行业"], "当前阶段": r["当前阶段"],
                         "预警级别": level, "触发规则": trig, "指标值": vals,
                         "建议": advice, "检查时间": r["检查时间"]})
        df_new = pd.DataFrame(rows)
        if os.path.exists(ALERTS_CSV):
            old = pd.read_csv(ALERTS_CSV)
            df = pd.concat([old, df_new], ignore_index=True)
        else:
            df = df_new
        df.to_csv(ALERTS_CSV, index=False, encoding="utf-8-sig")
        return ALERTS_CSV


def _print_report(results, report):
    print("=" * 72)
    print("  阶段3 预警引擎 — 全量检查结果")
    print("=" * 72)
    print(f"检查行业: {len(results)} 个 | 时间: {results[0]['检查时间']}")

    print(f"\n🔴 触发阶段转换 ({len(report['red'])}个):")
    if report["red"]:
        for r in report["red"]:
            print(f"   {r['行业']}({r['当前阶段']}): -> {', '.join(r['转换触发'])}")
    else:
        print("   (无)")

    print(f"\n🟡 领先信号预警-见底候选 ({len(report['yellow'])}个):")
    if report["yellow"]:
        for r in report["yellow"]:
            print(f"   {r['行业']}({r['当前阶段']}): {r['领先信号']['advice']}")
            for s in r["领先信号"]["signals"]:
                print(f"       {s}")
    else:
        print("   (无)")

    print(f"\n🟢 正常 ({len(report['green'])}个): {', '.join(r['行业'] for r in report['green'])}")

    print("\n22行业当前状态快照:")
    print(f"  {'行业':8s} {'当前阶段':8s} {'策略':14s} {'核心指标最新值':30s} 预警")
    print("  " + "-" * 80)
    for r in results:
        vals = "; ".join(f"{k.replace('_PE_TTM','PE').replace('期货价','')}={v:.0f}"
                         for k, v in r["核心指标"].items() if v is not None)[:30]
        lvl = "🔴转换" if r["转换触发"] else ("🟡见底" if r["领先信号"]["is_bottom_candidate"] else "🟢正常")
        print(f"  {r['行业']:8s} {r['当前阶段']:8s} {r['策略建议']:14s} {vals:30s} {lvl}")


def main():
    eng = AlertEngine()
    results = eng.run_full_check()
    report = eng.generate_alert_report(results)
    _print_report(results, report)
    path = eng.append_alerts_log(results)
    print(f"\n预警日志已追加: {path}")


if __name__ == "__main__":
    main()
