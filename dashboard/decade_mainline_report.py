#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 A：2015-2025 十年主线迁移全景报告
- 逐年调用 generate_annual_mainline_report() 生成单年报告
- 汇总为十年主线迁移全景 HTML（含热力图、甘特图、时代特征总结）

注：单年报告 CSV/HTML 文件名与 annual_mainline_report 实际产出一致
    ({year}_mainline_periods.csv / {year}_phases.csv / {year}_mainline_evolution.html)
"""

import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_data"
SW31_DIR = RAW_DIR / "sw31_daily"
REPORT_DIR = BASE_DIR / "dashboard" / "replay_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 申万 2014→2021 行业名称映射（用于统一跨年对比）
NAME_NORMALIZE = {
    "采掘": "煤炭",
    "电气设备": "电力设备",
    "休闲服务": "社会服务",
    "纺织服装": "纺织服饰",
    "商业贸易": "商贸零售",
}

ERA_LABELS = {
    2015: {"时代": "互联网+泡沫", "关键词": "互联网+、杠杆牛、股灾、创业板神话",
            "宏观": "降息降准、万众创业、场外配资"},
    2016: {"时代": "供给侧改革元年", "关键词": "供给侧改革、去产能、煤飞色舞、熔断",
            "宏观": "L型经济、去产能政策、房地产去库存"},
    2017: {"时代": "核心资产崛起", "关键词": "漂亮50、白酒家电、价值投资、外资入场",
            "宏观": "经济企稳、北上资金加速、金融去杠杆"},
    2018: {"时代": "去杠杆熊市", "关键词": "贸易战、质押爆仓、全面下跌、现金为王",
            "宏观": "中美贸易战、去杠杆、信用收缩"},
    2019: {"时代": "科技牛启动", "关键词": "半导体国产替代、5G、科创板、核心资产",
            "宏观": "贸易战缓和、科创板开板、LPR改革"},
    2020: {"时代": "疫情与流动性", "关键词": "新冠疫情、医药爆发、新能源起步、流动性泛滥",
            "宏观": "全球放水、疫情冲击+恢复、注册制推进"},
    2021: {"时代": "碳中和与新能源", "关键词": "碳中和、锂电光伏、煤炭暴涨、教育双减",
            "宏观": "碳达峰碳中和、大宗商品涨价、行业监管"},
    2022: {"时代": "地缘与衰退", "关键词": "俄乌战争、煤炭能源、信创自主可控、地产危机",
            "宏观": "美联储加息、俄乌冲突、地产暴雷"},
    2023: {"时代": "AI元年", "关键词": "ChatGPT、TMT爆发、中特估、量化监管",
            "宏观": "经济弱复苏、ChatGPT发布、地产持续调整"},
    2024: {"时代": "AI深化+924行情", "关键词": "Sora、924政策底、AI算力、红利资产",
            "宏观": "924政策组合拳、美联储降息、地产止跌企稳"},
    2025: {"时代": "AI应用落地", "关键词": "DeepSeek、机器人、有色暴涨、关税冲击",
            "宏观": "特朗普关税、DeepSeek开源、A股全面上涨"},
}


def generate_decade_report(start_year=2015, end_year=2025):
    from dashboard.annual_mainline_report import (
        generate_annual_mainline_report, load_sw31_data,
        calc_annual_industry_returns, identify_annual_true_mainlines,
    )

    print(f"\n{'='*70}")
    print(f"  {start_year}-{end_year} A 股十年主线迁移全景报告 v2（修复版）")
    print(f"  31 个申万一级行业 · 全年涨跌幅校验 · 综合评分体系")
    print(f"{'='*70}\n")

    all_years_data = {}

    # ── Step 1: 逐年生成单年报告(如未生成) ──
    for year in range(start_year, end_year + 1):
        print(f"\n{'─'*50}\n  处理 {year} 年...\n{'─'*50}")
        # 兼容查找: _v2 优先, 否则无后缀
        csv_v2 = RAW_DIR / f"{year}_mainline_periods_v2.csv"
        csv_v1 = RAW_DIR / f"{year}_mainline_periods.csv"
        csv_path = csv_v2 if csv_v2.exists() else (csv_v1 if csv_v1.exists() else None)

        if csv_path:
            print(f"  ✓ 已有 {year} 年数据，直接加载 ({csv_path.name})")
            ml_df = pd.read_csv(csv_path)
            sw_v2 = RAW_DIR / f"{year}_mainline_switches_v2.csv"
            sw_v1 = RAW_DIR / f"{year}_mainline_switches.csv"
            sw_path = sw_v2 if sw_v2.exists() else (sw_v1 if sw_v1.exists() else None)
            sw_df = pd.read_csv(sw_path) if sw_path else pd.DataFrame()
            ph_v2 = RAW_DIR / f"{year}_phases_v2.csv"
            ph_v1 = RAW_DIR / f"{year}_phases.csv"
            ph_path = ph_v2 if ph_v2.exists() else (ph_v1 if ph_v1.exists() else None)
            phase_df = pd.read_csv(ph_path) if ph_path else pd.DataFrame()
            all_years_data[year] = {"mainlines_df": ml_df, "switches_df": sw_df, "phases_df": phase_df}
        else:
            try:
                import io, contextlib
                with contextlib.redirect_stdout(io.StringIO()):
                    generate_annual_mainline_report(year)
                ml_df = pd.read_csv(csv_v1) if csv_v1.exists() else pd.DataFrame()
                sw_df = pd.read_csv(sw_v1) if sw_v1.exists() else pd.DataFrame()
                phase_df = pd.read_csv(ph_v1) if ph_v1.exists() else pd.DataFrame()
                all_years_data[year] = {"mainlines_df": ml_df, "switches_df": sw_df, "phases_df": phase_df}
                print(f"  ✓ {year} 年报告已生成")
            except Exception as e:
                print(f"  ✗ {year} 年生成失败: {repr(e)[:150]}")
                all_years_data[year] = {"mainlines_df": pd.DataFrame(),
                                        "switches_df": pd.DataFrame(),
                                        "phases_df": pd.DataFrame()}

    # ── Step 2: 全年真实涨跌幅校验 + 综合评分 ──
    print(f"\n{'='*50}\n  汇总十年数据（含全年涨幅校验）...\n{'='*50}\n")

    decade_summary = []
    year_top_industries = {}
    industry_year_map = {}

    for year in range(start_year, end_year + 1):
        data = all_years_data.get(year, {})
        ml_df = data.get("mainlines_df", pd.DataFrame()).copy()
        sw_df = data.get("switches_df", pd.DataFrame())
        phase_df = data.get("phases_df", pd.DataFrame())

        # 计算全年真实涨跌幅
        try:
            industry_data, _ = load_sw31_data(year)
            annual_returns = calc_annual_industry_returns(industry_data, year)
        except Exception:
            annual_returns = {}
        # 标准化 annual_returns 的 key
        annual_returns_norm = {NAME_NORMALIZE.get(k, k): v for k, v in annual_returns.items()}

        if ml_df.empty:
            if annual_returns_norm:
                top_annual = sorted(annual_returns_norm.items(), key=lambda x: x[1], reverse=True)
                best_name = top_annual[0][0] if top_annual else "-"
                best_ret = top_annual[0][1] if top_annual else 0
            else:
                best_name, best_ret = "-", 0
            decade_summary.append({"年份": year, "主线段数": 0, "切换次数": 0,
                                   "涉及行业": 0, "最强主线": best_name, "最强涨幅": best_ret,
                                   "时代": ERA_LABELS.get(year, {}).get("时代", "")})
            year_top_industries[year] = [(best_name, best_ret, 0)] if best_name != "-" else []
            continue

        if "行业" in ml_df.columns:
            ml_df["行业_标准"] = ml_df["行业"].map(lambda x: NAME_NORMALIZE.get(x, x))
        else:
            ml_df["行业_标准"] = ""

        n_mainlines = len(ml_df)
        n_switches = len(sw_df) if not sw_df.empty else 0

        # 构建主线列表用于评分
        mainlines_list = []
        for _, row in ml_df.iterrows():
            mainlines_list.append({"行业": row.get("行业_标准", row.get("行业", "")),
                                   "累计涨幅": row.get("累计涨幅", 0),
                                   "持续周数": row.get("持续周数", 0),
                                   "平均成交额占比": row.get("平均成交额占比", 0)})

        true_ranking = identify_annual_true_mainlines(mainlines_list, annual_returns_norm, top_n=5)

        if true_ranking:
            # 最强主线 = 评分TOP5 中全年涨幅最高者(兼顾主线持续性与全年真实表现)
            best_in_top = max(true_ranking, key=lambda x: x[2])
            best_name = best_in_top[0]
            best_annual_ret = best_in_top[2]
            best_segment_ret = best_in_top[3]
            best_weeks = best_in_top[4]
        else:
            if annual_returns_norm:
                top = max(annual_returns_norm.items(), key=lambda x: x[1])
                best_name, best_annual_ret = top
            else:
                best_name, best_annual_ret = "-", 0
            best_segment_ret, best_weeks = 0, 0

        unique_industries = len(set(r[0] for r in true_ranking)) if true_ranking else 0

        decade_summary.append({"年份": year, "主线段数": n_mainlines, "切换次数": n_switches,
                               "涉及行业": unique_industries, "最强主线": best_name,
                               "最强涨幅": best_annual_ret, "最大单段": best_segment_ret,
                               "总周数": best_weeks,
                               "时代": ERA_LABELS.get(year, {}).get("时代", "")})

        year_tops = []
        for r in true_ranking:
            ind, score, annual_ret, seg_ret, weeks, n_seg = r
            year_tops.append((ind, annual_ret, weeks))
            industry_year_map.setdefault(ind, set()).add(year)
        # 按全年涨幅降序, 让 TOP1 与"最强主线"口径一致
        year_tops.sort(key=lambda x: x[1], reverse=True)
        year_top_industries[year] = year_tops

        print(f"  {year} | 最强: {best_name} (全年+{best_annual_ret:.1f}%, "
              f"最大单段+{best_segment_ret:.1f}%, {best_weeks}周)")
        if annual_returns_norm:
            top3_annual = sorted(annual_returns_norm.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"    全年涨幅 TOP3: " + " | ".join(f"{n}+{v:.1f}%" for n, v in top3_annual))

    for k in industry_year_map:
        industry_year_map[k] = sorted(industry_year_map[k])

    # ── Step 3: 生成 HTML ──
    print(f"\n  生成 HTML 报告...")
    html = _build_decade_html(decade_summary, year_top_industries, industry_year_map,
                              all_years_data, start_year, end_year)
    html_path = REPORT_DIR / f"{start_year}_{end_year}_decade_mainline_v2.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    summary_df = pd.DataFrame(decade_summary)
    csv_path = RAW_DIR / f"{start_year}_{end_year}_decade_summary_v2.csv"
    summary_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\n  ✓ HTML: {html_path} ({os.path.getsize(html_path)/1024:.0f} KB)")
    print(f"  ✓ CSV: {csv_path}")

    print(f"\n{'='*70}\n  {start_year}-{end_year} 十年主线迁移摘要（v2 修复版）\n{'='*70}")
    for s in decade_summary:
        print(f"\n  {s['年份']} | {s['时代']}")
        print(f"    最强主线: {s['最强主线']} (全年{s['最强涨幅']:+.1f}%)")
        tops = year_top_industries.get(s["年份"], [])
        if tops:
            print(f"    TOP3: " + " | ".join(f"{t[0]}{t[1]:+.0f}%" for t in tops[:3]))

    print(f"\n  十年主线频率 TOP10:")
    freq = sorted(industry_year_map.items(), key=lambda x: len(x[1]), reverse=True)
    for ind, years in freq[:10]:
        print(f"    {ind}: {len(years)}年 ({', '.join(map(str, years))})")
    print(f"\n{'='*70}\n")
    return all_years_data


def _generate_decade_report_legacy(start_year=2015, end_year=2025):
    from dashboard.annual_mainline_report import generate_annual_mainline_report

    print(f"\n{'='*70}")
    print(f"  {start_year}-{end_year} A 股十年主线迁移全景报告")
    print(f"  31 个申万一级行业 · {end_year - start_year + 1} 年全景")
    print(f"{'='*70}\n")

    all_years_data = {}

    for year in range(start_year, end_year + 1):
        print(f"\n{'─'*50}\n  处理 {year} 年...\n{'─'*50}")

        # 检查是否已有单年 CSV(与 annual_mainline_report 产出文件名一致)
        csv_path = RAW_DIR / f"{year}_mainline_periods.csv"
        if csv_path.exists():
            print(f"  ✓ 已有 {year} 年数据，直接加载")
            ml_df = pd.read_csv(csv_path)
            sw_csv = RAW_DIR / f"{year}_mainline_switches.csv"
            sw_df = pd.read_csv(sw_csv) if sw_csv.exists() else pd.DataFrame()
            phase_csv = RAW_DIR / f"{year}_phases.csv"
            phase_df = pd.read_csv(phase_csv) if phase_csv.exists() else pd.DataFrame()
            all_years_data[year] = {"mainlines_df": ml_df, "switches_df": sw_df, "phases_df": phase_df}
        else:
            try:
                # 抑制单年报告的海量打印
                import io, contextlib
                with contextlib.redirect_stdout(io.StringIO()):
                    generate_annual_mainline_report(year)
                ml_df = pd.read_csv(RAW_DIR / f"{year}_mainline_periods.csv")
                sw_df = pd.read_csv(RAW_DIR / f"{year}_mainline_switches.csv") if (RAW_DIR / f"{year}_mainline_switches.csv").exists() else pd.DataFrame()
                phase_df = pd.read_csv(RAW_DIR / f"{year}_phases.csv") if (RAW_DIR / f"{year}_phases.csv").exists() else pd.DataFrame()
                all_years_data[year] = {"mainlines_df": ml_df, "switches_df": sw_df, "phases_df": phase_df}
                print(f"  ✓ {year} 年报告已生成")
            except Exception as e:
                print(f"  ✗ {year} 年生成失败: {repr(e)[:150]}")
                all_years_data[year] = {"mainlines_df": pd.DataFrame(),
                                        "switches_df": pd.DataFrame(),
                                        "phases_df": pd.DataFrame()}

    print(f"\n{'='*50}\n  汇总十年数据...\n{'='*50}\n")

    decade_summary = []
    year_top_industries = {}
    industry_year_map = {}

    for year in range(start_year, end_year + 1):
        data = all_years_data.get(year, {})
        ml_df = data.get("mainlines_df", pd.DataFrame()).copy()
        sw_df = data.get("switches_df", pd.DataFrame())
        phase_df = data.get("phases_df", pd.DataFrame())

        if ml_df.empty:
            decade_summary.append({"年份": year, "主线段数": 0, "切换次数": 0,
                                   "涉及行业": 0, "最强主线": "-", "最强涨幅": 0,
                                   "时代": ERA_LABELS.get(year, {}).get("时代", "")})
            year_top_industries[year] = []
            continue

        if "行业" in ml_df.columns:
            ml_df["行业_标准"] = ml_df["行业"].map(lambda x: NAME_NORMALIZE.get(x, x))
        else:
            ml_df["行业_标准"] = ""

        n_mainlines = len(ml_df)
        n_switches = len(sw_df) if not sw_df.empty else 0
        unique_industries = ml_df["行业_标准"].nunique() if "行业_标准" in ml_df.columns else 0

        best_name, best_return = "-", 0
        if "累计涨幅" in ml_df.columns and not ml_df.empty:
            best_idx = ml_df["累计涨幅"].idxmax()
            best_name = ml_df.loc[best_idx, "行业_标准"] if "行业_标准" in ml_df.columns else "-"
            best_return = ml_df.loc[best_idx, "累计涨幅"]

        decade_summary.append({"年份": year, "主线段数": n_mainlines, "切换次数": n_switches,
                               "涉及行业": unique_industries, "最强主线": best_name,
                               "最强涨幅": best_return,
                               "时代": ERA_LABELS.get(year, {}).get("时代", "")})

        if "累计涨幅" in ml_df.columns and "行业_标准" in ml_df.columns:
            top5 = ml_df.nlargest(5, "累计涨幅")
            year_tops = []
            for _, row in top5.iterrows():
                ind = row["行业_标准"]
                ret = row["累计涨幅"]
                weeks = row.get("持续周数", 0)
                year_tops.append((ind, ret, weeks))
                # 频率统计: 同年只计一次(set 去重)
                yrs = industry_year_map.setdefault(ind, set())
                yrs.add(year)
            year_top_industries[year] = year_tops
        else:
            year_top_industries[year] = []

    print("  生成 HTML 报告...")
    html = _build_decade_html(decade_summary, year_top_industries, industry_year_map,
                              all_years_data, start_year, end_year)
    html_path = REPORT_DIR / f"{start_year}_{end_year}_decade_mainline.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    summary_df = pd.DataFrame(decade_summary)
    csv_path = RAW_DIR / f"{start_year}_{end_year}_decade_summary.csv"
    summary_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\n  ✓ 十年全景 HTML: {html_path} ({os.path.getsize(html_path)/1024:.0f} KB)")
    print(f"  ✓ 十年汇总 CSV: {csv_path}")

    print(f"\n{'='*70}\n  {start_year}-{end_year} 十年主线迁移摘要\n{'='*70}")
    for s in decade_summary:
        print(f"\n  {s['年份']} | {s['时代']}")
        print(f"    主线 {s['主线段数']} 段, 切换 {s['切换次数']} 次, 涉及 {s['涉及行业']} 行业")
        print(f"    最强: {s['最强主线']} +{s['最强涨幅']:.1f}%")
        tops = year_top_industries.get(s["年份"], [])
        if tops:
            print(f"    TOP3: " + " | ".join(f"{t[0]}+{t[1]:.0f}%" for t in tops[:3]))

    print(f"\n  十年主线出现频率 TOP10:")
    freq = sorted(industry_year_map.items(), key=lambda x: len(x[1]), reverse=True)
    for ind, years in freq[:10]:
        print(f"    {ind}: {len(years)}年 ({', '.join(map(str, sorted(years)))})")
    print(f"\n{'='*70}\n")
    return all_years_data


def _build_decade_html(decade_summary, year_top_industries, industry_year_map,
                       all_years_data, start_year, end_year):
    css = """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
               background: #0a0e17; color: #e0e0e0; padding: 20px; max-width: 1600px; margin: 0 auto; }
        .header { text-align: center; padding: 40px 20px;
                  background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
                  border-radius: 16px; margin-bottom: 30px; }
        .header h1 { font-size: 36px; color: #ffd700; margin-bottom: 10px; }
        .header p { font-size: 16px; color: #8899aa; }
        .section-title { font-size: 24px; font-weight: bold; color: #ffd700;
                          margin: 30px 0 15px; padding-left: 15px; border-left: 4px solid #ffd700; }
        .year-card { background: #111827; border-radius: 12px; margin-bottom: 20px;
                     overflow: hidden; border: 1px solid #1f2937; }
        .year-header { padding: 15px 25px; display: flex; justify-content: space-between;
                       align-items: center; flex-wrap: wrap; gap: 10px; cursor: pointer; }
        .year-header:hover { background: #1a2332; }
        .year-title { font-size: 22px; font-weight: bold; }
        .era-badge { padding: 5px 14px; border-radius: 20px; font-size: 13px; font-weight: bold; }
        .year-body { padding: 15px 25px; display: none; }
        .year-body.show { display: block; }
        .freq-bar { height: 20px; border-radius: 4px; display: flex; align-items: center;
                    padding: 0 8px; font-size: 11px; color: white; font-weight: bold; }
        .insight-box { background: #1a2332; border-radius: 12px; padding: 20px;
                       margin-bottom: 15px; border: 1px solid #2a3555; }
        .insight-box h3 { color: #ffd700; margin-bottom: 10px; font-size: 16px; }
        .insight-box p { font-size: 14px; line-height: 1.8; color: #d1d5db; }
        .tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin: 2px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .gantt-row { display: flex; align-items: center; height: 26px; margin: 2px 0; }
        .gantt-label { width: 80px; font-size: 11px; text-align: right; padding-right: 8px; white-space: nowrap; overflow: hidden; }
        .gantt-bar-container { flex: 1; position: relative; height: 18px; background: #0d1117; border-radius: 4px; }
        .gantt-bar { position: absolute; height: 100%; border-radius: 4px; display: flex; align-items: center; padding: 0 6px; font-size: 9px; color: white; font-weight: bold; }
        @media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
    </style>
    <script>
    function toggleYear(id) {
        var el = document.getElementById(id);
        if (el) el.classList.toggle('show');
    }
    </script>
    """

    total_mainlines = sum(s["主线段数"] for s in decade_summary)
    total_switches = sum(s["切换次数"] for s in decade_summary)
    total_industries = len(industry_year_map)
    freq_sorted = sorted(industry_year_map.items(), key=lambda x: len(x[1]), reverse=True)
    most_freq = freq_sorted[0] if freq_sorted else ("", [])

    overview_html = f"""
    <div style="display:flex;gap:15px;flex-wrap:wrap;justify-content:center;margin-bottom:30px">
        <div style="background:#151b2e;border-radius:12px;padding:20px;min-width:150px;text-align:center;border:1px solid #2a3555"><div style="font-size:28px;font-weight:bold;color:#ffd700">{end_year - start_year + 1}</div><div style="font-size:13px;color:#8899aa">覆盖年份</div></div>
        <div style="background:#151b2e;border-radius:12px;padding:20px;min-width:150px;text-align:center;border:1px solid #2a3555"><div style="font-size:28px;font-weight:bold;color:#ffd700">{total_mainlines}</div><div style="font-size:13px;color:#8899aa">主线段落总计</div></div>
        <div style="background:#151b2e;border-radius:12px;padding:20px;min-width:150px;text-align:center;border:1px solid #2a3555"><div style="font-size:28px;font-weight:bold;color:#ffd700">{total_switches}</div><div style="font-size:13px;color:#8899aa">切换事件总计</div></div>
        <div style="background:#151b2e;border-radius:12px;padding:20px;min-width:150px;text-align:center;border:1px solid #2a3555"><div style="font-size:28px;font-weight:bold;color:#ffd700">{total_industries}</div><div style="font-size:13px;color:#8899aa">涉及行业</div></div>
        <div style="background:#151b2e;border-radius:12px;padding:20px;min-width:150px;text-align:center;border:1px solid #2a3555"><div style="font-size:20px;font-weight:bold;color:#ffd700">{most_freq[0]}</div><div style="font-size:13px;color:#8899aa">最频繁主线（{len(most_freq[1])}年）</div></div>
    </div>"""

    era_colors = {
        "互联网+泡沫": "#ef4444", "供给侧改革元年": "#f59e0b", "核心资产崛起": "#3b82f6",
        "去杠杆熊市": "#6b7280", "科技牛启动": "#8b5cf6", "疫情与流动性": "#ec4899",
        "碳中和与新能源": "#22c55e", "地缘与衰退": "#64748b", "AI元年": "#06b6d4",
        "AI深化+924行情": "#0ea5e9", "AI应用落地": "#fbbf24",
    }

    year_cards = ""
    for s in decade_summary:
        year = s["年份"]
        era = ERA_LABELS.get(year, {})
        era_name = era.get("时代", "")
        era_kw = era.get("关键词", "")
        era_macro = era.get("宏观", "")
        era_color = era_colors.get(era_name, "#6b7280")
        tops = year_top_industries.get(year, [])
        top_tags = ""
        for ind, ret, weeks in tops[:5]:
            top_tags += f'<span class="tag" style="background:#1a2332;color:#d1d5db;border:1px solid #2a3555">{ind} <span style="color:{ "#ef4444" if ret > 0 else "#22c55e"}">{"+" if ret > 0 else ""}{ret:.1f}%</span> ({weeks}周)</span>'
        phase_df = all_years_data.get(year, {}).get("phases_df", pd.DataFrame())
        phase_items = ""
        if not phase_df.empty and "活跃主线" in phase_df.columns:
            for _, row in phase_df.iterrows():
                phase_items += f'<div style="padding:6px 0;border-bottom:1px solid #1f2937;font-size:12px"><strong>阶段 {row.get("阶段", "")}</strong> {row.get("开始", "")} → {row.get("结束", "")} ({row.get("天数", "")}天) | {row.get("大盘状态", "")}<br><span style="color:#8899aa">主线: {row.get("活跃主线", "")}</span></div>'
        year_id = f"year_{year}"
        year_cards += f"""
        <div class="year-card">
            <div class="year-header" onclick="toggleYear('{year_id}')">
                <div><span class="year-title" style="color:{era_color}">{year}</span>
                <span class="era-badge" style="background:{era_color}20;color:{era_color};border:1px solid {era_color}">{era_name}</span>
                <span style="font-size:13px;color:#8899aa;margin-left:10px">{s['主线段数']}段主线 · {s['切换次数']}次切换 · 最强 {s['最强主线']} {s['最强涨幅']:+.1f}%</span></div>
                <span style="color:#6b7280;font-size:14px">▼ 展开</span>
            </div>
            <div id="{year_id}" class="year-body">
                <div class="grid-2">
                    <div><h4 style="color:#8899aa;margin-bottom:8px">🏷️ 关键词</h4><p style="font-size:13px;color:#d1d5db">{era_kw}</p>
                        <h4 style="color:#8899aa;margin:12px 0 8px">📈 宏观背景</h4><p style="font-size:13px;color:#d1d5db">{era_macro}</p></div>
                    <div><h4 style="color:#8899aa;margin-bottom:8px">🔥 TOP5 主线</h4><div>{top_tags if top_tags else '<span style="color:#6b7280">无数据</span>'}</div></div>
                </div>
                <div style="margin-top:15px"><h4 style="color:#8899aa;margin-bottom:8px">📅 阶段详情</h4>
                    <div style="max-height:300px;overflow-y:auto">{phase_items}</div>
                    <p style="margin-top:10px"><a href="{year}_mainline_evolution.html" style="color:#00d4ff;text-decoration:none">→ 查看 {year} 年完整报告</a></p></div>
            </div>
        </div>"""

    # 行业频率
    freq_html = ""
    max_freq = len(freq_sorted[0][1]) if freq_sorted else 1
    for ind, years in freq_sorted[:20]:
        bar_w = len(years) / max_freq * 100
        years_str = ", ".join(map(str, sorted(years)))
        if ind in ["电子", "计算机", "通信", "传媒"]:
            color = "#3b82f6"
        elif ind in ["有色金属", "煤炭", "钢铁", "基础化工", "石油石化"]:
            color = "#f59e0b"
        elif ind in ["食品饮料", "医药生物", "家用电器", "社会服务"]:
            color = "#ec4899"
        elif ind in ["电力设备", "机械设备", "汽车"]:
            color = "#22c55e"
        elif ind in ["银行", "非银金融", "房地产"]:
            color = "#8b5cf6"
        else:
            color = "#6b7280"
        freq_html += f'<div style="display:flex;align-items:center;margin:4px 0"><div style="width:80px;text-align:right;padding-right:8px;font-size:12px;font-weight:bold;color:{color}">{ind}</div><div style="flex:1"><div class="freq-bar" style="width:{bar_w:.1f}%;background:{color}">{len(years)}年</div></div><div style="width:200px;font-size:10px;color:#8899aa;padding-left:8px">{years_str}</div></div>'

    # 甘特图
    gantt_html = ""
    for year in range(start_year, end_year + 1):
        tops = year_top_industries.get(year, [])[:3]
        if not tops:
            continue
        era_color = era_colors.get(ERA_LABELS.get(year, {}).get("时代", ""), "#6b7280")
        gantt_html += f'<div style="margin:8px 0"><div style="font-size:13px;font-weight:bold;color:{era_color};margin-bottom:4px">{year} · {ERA_LABELS.get(year, {}).get("时代", "")}</div>'
        for ind, ret, weeks in tops:
            bar_w = min(weeks * 3, 80)
            color = "#ef4444" if ret > 20 else ("#f59e0b" if ret > 10 else ("#3b82f6" if ret > 0 else "#6b7280"))
            gantt_html += f'<div class="gantt-row"><div class="gantt-label">{ind}</div><div class="gantt-bar-container"><div class="gantt-bar" style="width:{bar_w:.1f}%;background:{color};left:0">+{ret:.0f}% / {weeks}周</div></div></div>'
        gantt_html += "</div>"

    # 洞察
    evergreen = [ind for ind, yrs in freq_sorted if len(yrs) >= 5]
    oneshot = [ind for ind, yrs in freq_sorted if len(yrs) == 1]
    switch_vals = [s["切换次数"] for s in decade_summary]
    avg_switches = np.mean(switch_vals) if switch_vals else 0
    recent_avg = np.mean(switch_vals[-3:]) if len(switch_vals) >= 3 else 0
    trend_note = "近年切换加速，风格轮动更快，需更频繁动态调仓" if recent_avg > avg_switches else "近年切换放缓，主线持续性增强，可拉长持仓周期"

    insights_html = f"""
    <div class="insight-box"><h3>🕰️ 十年主线时代特征演变</h3><p>
        2015-2016：<strong>政策驱动</strong>（互联网+、供给侧改革），主线为计算机/传媒/周期。<br>
        2017-2018：<strong>价值回归</strong>（核心资产、外资定价），主线为食品饮料/家电/银行。<br>
        2019-2020：<strong>科技崛起</strong>（国产替代、5G），主线为电子/半导体/医药。<br>
        2021-2022：<strong>能源革命</strong>（碳中和、地缘），主线为电力设备/煤炭/有色。<br>
        2023-2025：<strong>AI 浪潮</strong>（ChatGPT/DeepSeek），主线为计算机/通信/电子。<br>
        每轮主线跨度约 2-3 年，核心驱动力从政策→价值→科技→能源→AI 逐步演进。
    </p></div>
    <div class="insight-box"><h3>🌲 常青行业 vs 昙花一现</h3><p>
        <strong>常青行业（≥5年出现）</strong>：{', '.join(evergreen) if evergreen else '无'}。具备跨周期资金吸引力，是配置型资金长期目标。<br>
        <strong>昙花行业（仅1年出现）</strong>：{', '.join(oneshot) if oneshot else '无'}。通常由单一事件驱动，持续性弱，适合事件驱动交易而非持仓。
    </p></div>
    <div class="insight-box"><h3>🔄 切换频率十年趋势</h3><p>
        十年平均每年 {avg_switches:.1f} 次切换，近三年平均 {recent_avg:.1f} 次。{trend_note}。
    </p></div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{start_year}-{end_year} A 股十年主线迁移全景</title>{css}</head>
<body>
    <div class="header"><h1>🏆 {start_year}-{end_year} A 股十年主线迁移全景</h1>
        <p>31 个申万一级行业 · {end_year - start_year + 1} 年逐年分析 · 主线演变与时代特征</p>
        <p style="margin-top:8px;color:#6b7280">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p></div>
    {overview_html}
    <div class="section-title">📊 十年洞察</div>{insights_html}
    <div class="section-title">📅 逐年主线演变（点击展开）</div>{year_cards}
    <div class="section-title">📊 行业主线出现频率排名</div>
    <div style="background:#111827;border-radius:12px;padding:20px;border:1px solid #1f2937">{freq_html}</div>
    <div class="section-title">📊 十年 TOP3 主线甘特图</div>
    <div style="background:#111827;border-radius:12px;padding:20px;border:1px solid #1f2937">{gantt_html}</div>
</body></html>"""
    return html


if __name__ == "__main__":
    start = 2015
    end = 2025
    if len(sys.argv) > 1:
        try:
            start = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        try:
            end = int(sys.argv[2])
        except ValueError:
            pass
    generate_decade_report(start, end)
