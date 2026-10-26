#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产能周期择时策略 - 批量回测引擎 (阶段2)
================================================
- 读取22行业，每个行业跑 binary/aggressive/conservative 三模式
- 汇总到 DataFrame，按 A组(2015起)/B组(2021起) 分别统计
- 输出:
    cycle_timing_summary.csv     22行业三模式汇总
    phase_effectiveness.csv      6周期阶段效果验证
    deviation_analysis.csv       deviation_type 影响分析
"""
import os
import sys
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "backtest"))
from cycle_timing_strategy import CycleTimingBacktest, POSITION_RULES

MAPPING_PATH = os.path.join(BASE_DIR, "raw_data", "sw_index_mapping.json")
CYCLE_CSV = os.path.join(BASE_DIR, "raw_data", "industry_cycle.csv")
OUT_DIR = os.path.join(BASE_DIR, "backtest", "backtest_results")

MODES = ["binary", "aggressive", "conservative"]


def group_of(start_date):
    """A组=2016前起，B组=2016后起(即2021起短周期)"""
    return "A" if str(start_date) < "2016-01-01" else "B"


def run_all():
    os.makedirs(OUT_DIR, exist_ok=True)
    mapping = json.load(open(MAPPING_PATH, encoding="utf-8"))
    # 以周期CSV的22个行业为准（每个都有周期标注）。
    # 周期口径用 "有色金属/通信设备"，日线已补提；舍弃无标注的 "钢铁/养殖业"。
    cycle_df = pd.read_csv(CYCLE_CSV)
    industries = sorted(cycle_df["行业名称"].astype(str).unique())
    # 组别判定：用映射里的覆盖起始；若不在映射(如有色/通信)，用其日线起始
    def _group(ind):
        if ind in mapping:
            return group_of(mapping[ind]["coverage"].split("~")[0].strip())
        # 读 index_daily 起始
        p = os.path.join(BASE_DIR, "raw_data", "index_daily", f"{ind}.csv")
        try:
            first = pd.read_csv(p, nrows=1)["date"][0]
            return group_of(first)
        except Exception:
            return "A"

    summary_rows = []
    all_phase_returns = []   # 用于 phase_effectiveness
    all_reports = {}         # industry -> report(dict)，供画图
    print(f"=== 批量回测 {len(industries)} 个行业 x {len(MODES)} 模式 ===")
    for idx, ind in enumerate(industries, 1):
        try:
            bt = CycleTimingBacktest(ind)
            group = _group(ind)
            # 主报告用 binary
            rep = bt.generate_report("binary")
            all_reports[ind] = {"group": group, "binary": rep}
            m = rep["metrics"]
            segs = rep["segments"]

            # 收集有数据的周期段（基准收益，用于阶段效果验证）
            pr = m["phase_returns"]
            for r in pr:
                r["industry"] = ind
                r["group"] = group
                all_phase_returns.append(r)

            n_with = int((segs["trading_days"] > 0).sum())
            n_without = int((segs["trading_days"] == 0).sum())

            row = {
                "行业名称": ind,
                "数据组别": group,
                "回测起始日": rep["data_start"],
                "回测结束日": rep["data_end"],
                "交易日数": rep["n_trading_days"],
                "周期段数_含数据": n_with,
                "周期段数_无数据": n_without,
                "binary_年化收益": round(m["annual_return"], 2),
                "binary_基准年化": round(m["benchmark_annual"], 2),
                "binary_超额年化": round(m["excess_annual_return"], 2),
                "binary_最大回撤": round(m["max_drawdown"], 2),
                "binary_基准回撤": round(m["benchmark_max_drawdown"], 2),
                "binary_夏普": round(m["sharpe_ratio"], 3),
                "binary_胜率": round(m["win_rate_by_phase"], 1),
            }
            # aggressive / conservative
            for mode in ["aggressive", "conservative"]:
                lab, s_nav, b_nav = bt.run_backtest(mode)
                mm = bt.calc_metrics(s_nav, b_nav)
                row[f"{mode}_年化收益"] = round(mm["annual_return"], 2)
                row[f"{mode}_超额年化"] = round(mm["excess_annual_return"], 2)
                all_reports[ind][mode] = {"metrics": mm, "labeled": lab,
                                          "strategy_nav": s_nav, "benchmark_nav": b_nav}
            summary_rows.append(row)
            print(f"  [{idx:2d}/22] {ind:8s}[{group}] 策略年化{m['annual_return']:+6.2f}% "
                  f"基准{m['benchmark_annual']:+6.2f}% 超额{m['excess_annual_return']:+6.2f}% "
                  f"夏普{m['sharpe_ratio']:.2f} 回撤{m['max_drawdown']:.1f}%")
        except Exception as e:
            print(f"  [{idx:2d}/22] {ind:8s} 失败: {repr(e)[:120]}")
            summary_rows.append({"行业名称": ind, "数据组别": _group(ind), "error": str(e)})

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(os.path.join(OUT_DIR, "cycle_timing_summary.csv"),
                      index=False, encoding="utf-8-sig")

    phase_df = pd.DataFrame(all_phase_returns)
    return summary_df, phase_df, all_reports


# ---------- 4b. 周期阶段效果验证 ----------
def phase_effectiveness(phase_df):
    """按周期阶段分组，统计基准收益（验证假说）"""
    if phase_df.empty:
        return pd.DataFrame()
    phase_df = phase_df.copy()
    phase_df["years"] = phase_df["days"] / 252.0
    # 段年化基准收益
    phase_df["bench_annual"] = np.where(
        phase_df["years"] > 0,
        ((1 + phase_df["benchmark_ret"] / 100) ** (1 / phase_df["years"]) - 1) * 100,
        np.nan)
    g = phase_df.groupby("phase")["bench_annual"]
    out = pd.DataFrame({
        "平均基准年化%": g.mean().round(2),
        "中位数年化%": g.median().round(2),
        "正收益占比%": (g.apply(lambda s: (s > 0).mean() * 100)).round(1),
        "样本段数": g.count(),
    }).reset_index()
    # 期望排序
    order = ["成长期", "复苏期", "成熟稳定期", "景气顶部", "过剩期", "出清期"]
    out["__o"] = out["phase"].map({k: i for i, k in enumerate(order)})
    out = out.sort_values("__o").drop(columns="__o").reset_index(drop=True)
    out.to_csv(os.path.join(OUT_DIR, "phase_effectiveness.csv"),
               index=False, encoding="utf-8-sig")
    return out


# ---------- 4c. deviation_type 分析 ----------
def deviation_analysis(phase_df):
    """对有 deviation_type 的周期段，分析策略误判"""
    if phase_df.empty:
        return pd.DataFrame()
    dev = phase_df[phase_df["deviation_type"].astype(str).str.len() > 0].copy()
    if dev.empty:
        return pd.DataFrame()
    # 预期方向：成长/复苏/成熟/景气顶部 期望基准正(策略做多)；过剩/出清 期望基准负(策略空仓正确)
    bullish = {"成长期", "复苏期", "成熟稳定期", "景气顶部"}
    dev["预期方向"] = dev["phase"].apply(lambda p: "多" if p in bullish else "空")
    # 误判：在"偏离"段，基准实际方向与预期相反，导致策略择时出错
    dev["基准方向"] = np.where(dev["benchmark_ret"] > 0, "涨", "跌")
    dev["策略误判"] = ((dev["预期方向"] == "多") & (dev["基准方向"] == "跌")) | \
                    ((dev["预期方向"] == "空") & (dev["基准方向"] == "涨"))
    # 超额损失 = 基准收益 - 策略收益（正值=策略跑输基准）
    dev["超额损失%"] = (dev["benchmark_ret"] - dev["strategy_ret"]).round(2)

    g = dev.groupby("deviation_type")
    out = pd.DataFrame({
        "段数": g.size(),
        "策略误判率%": (g["策略误判"].mean() * 100).round(1),
        "平均超额损失%": g["超额损失%"].mean().round(2),
        "平均基准收益%": g["benchmark_ret"].mean().round(2),
        "平均策略收益%": g["strategy_ret"].mean().round(2),
    }).reset_index().rename(columns={"deviation_type": "deviation_type"})
    out = out.sort_values("平均超额损失%", ascending=False).reset_index(drop=True)
    out.to_csv(os.path.join(OUT_DIR, "deviation_analysis.csv"),
               index=False, encoding="utf-8-sig")
    return out, dev


if __name__ == "__main__":
    summary_df, phase_df, reports = run_all()
    print("\n=== 周期阶段效果验证 ===")
    pe = phase_effectiveness(phase_df)
    print(pe.to_string(index=False))
    print("\n=== deviation_type 影响分析 ===")
    res = deviation_analysis(phase_df)
    if isinstance(res, tuple):
        print(res[0].to_string(index=False))
    # 保存 reports 供画图用
    import pickle
    with open(os.path.join(OUT_DIR, "_reports.pkl"), "wb") as f:
        # 只存必要字段，避免存整 labeled
        slim = {}
        for ind, r in reports.items():
            slim[ind] = {"group": r["group"],
                         "data_start": r["binary"]["data_start"],
                         "data_end": r["binary"]["data_end"]}
            for mode in MODES:
                rec = r.get(mode)
                if rec is None or "labeled" not in rec:
                    continue
                if mode == "binary":
                    lab = rec["labeled"][["date", "strategy_nav", "benchmark_nav",
                                          "phase", "position", "deviation_type"]].copy()
                    lab["date"] = lab["date"].astype(str)
                    slim[ind][mode] = {"metrics": rec["metrics"], "labeled": lab}
                else:
                    lab = rec["labeled"][["date", "strategy_nav", "benchmark_nav"]].copy()
                    lab["date"] = lab["date"].astype(str)
                    slim[ind][mode] = {"metrics": rec["metrics"], "labeled": lab}
        pickle.dump(slim, f)
    print(f"\n已保存 _reports.pkl 供画图使用。汇总表 {len(summary_df)} 行。")
