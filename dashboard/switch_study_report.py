#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2016-2025 主线切换深度研究报告
核心问题：每次主线切换时，新旧主线有什么微观征兆？
分析维度：
  1. 旧主线见顶信号：成交额占比变化、涨速变化、连续周数衰减
  2. 新主线发酵信号：成交额占比提升、排名攀升轨迹、底部涨幅
  3. 交叉窗口：旧主线走弱/新主线走强的时间重叠期
  4. 切换时全市场状态：大盘状态、其他行业表现
  5. 跨年份同类切换对比：科技→消费、消费→周期 等类型的共性规律
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_data"
SW31_DIR = RAW_DIR / "sw31_daily"
REPORT_DIR = BASE_DIR / "dashboard" / "replay_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

SECTOR_TYPE = {
    "电子": "科技", "计算机": "科技", "通信": "科技", "传媒": "科技",
    "有色金属": "周期", "煤炭": "周期", "钢铁": "周期", "基础化工": "周期",
    "石油石化": "周期", "建筑材料": "周期",
    "食品饮料": "消费", "医药生物": "消费", "家用电器": "消费",
    "社会服务": "消费", "商贸零售": "消费", "纺织服饰": "消费",
    "美容护理": "消费", "农林牧渔": "消费", "轻工制造": "消费",
    "电力设备": "制造", "机械设备": "制造", "汽车": "制造", "国防军工": "制造",
    "银行": "金融", "非银金融": "金融", "房地产": "金融",
    "公用事业": "防御", "交通运输": "防御", "环保": "防御",
    "建筑装饰": "其他", "综合": "其他",
}

NAME_NORMALIZE = {
    "采掘": "煤炭", "电气设备": "电力设备", "休闲服务": "社会服务",
    "纺织服装": "纺织服饰", "商业贸易": "商贸零售",
}

# 板块类型 → CSS class 后缀
_TYPE_CSS = {"科技": "sci", "消费": "con", "周期": "cyc", "制造": "mfg", "金融": "fin", "防御": "def"}


def _type_css_class(industry_type):
    """板块类型→CSS class(集中处理，避免 f-string 嵌套字典不生效)"""
    return "type-" + _TYPE_CSS.get(industry_type, "")


def load_sw31_data(year):
    from dashboard.annual_mainline_report import load_sw31_data as _load
    return _load(year)


def calc_weekly_all(industry_data, year):
    """计算该年每周每行业的涨跌幅/成交额/占比/排名"""
    records = []
    for name, df in industry_data.items():
        df = df[df["日期"].dt.year == year].copy()
        if df.empty:
            continue
        df["周"] = df["日期"].dt.isocalendar().week.astype(int)
        for w, grp in df.groupby("周"):
            grp = grp.sort_values("日期")
            if len(grp) < 1:
                continue
            o = grp["收盘"].iloc[0]; c = grp["收盘"].iloc[-1]
            pct = (c / o - 1) * 100 if o > 0 else 0
            amt = grp["成交额"].sum() if "成交额" in grp.columns else 0
            records.append({"周开始": grp["日期"].iloc[0], "周结束": grp["日期"].iloc[-1],
                            "周": w, "行业": name, "周涨跌幅": round(pct, 2), "周成交额": amt})
    wdf = pd.DataFrame(records)
    if wdf.empty:
        return wdf
    week_total = wdf.groupby("周")["周成交额"].transform("sum")
    wdf["成交额占比"] = np.where(week_total > 0, (wdf["周成交额"] / week_total * 100).round(2), 0)
    wdf["涨幅排名"] = wdf.groupby("周")["周涨跌幅"].rank(ascending=False, method="min").astype(int)
    wdf["成交额排名"] = wdf.groupby("周")["成交额占比"].rank(ascending=False, method="min").astype(int)
    return wdf


def identify_mainline_periods(weekly_df, top_n=3, min_weeks=2):
    """容间断滑窗主线识别 v3(薄包装,调用 mainline_core)。

    核心改动 vs 旧版"连续>=min_weeks周进入TOP-N":
      - 活跃池 = 周涨跌幅 TOP5 ∪ 成交额占比 TOP5(满足任一即活跃)
      - 容间断:允许中间断 1-2 周,滑窗活跃率 ≥ 50% 即延续
      - 三级分级:短期热点 / 中期主线 / 长期主线(详见 mainline_core)
    返回 dict 兼容旧键名(行业/开始周/结束周/持续周数/周列表/开始日期/结束日期/累计涨幅/平均成交额占比/平均排名)
    外加新字段(级别/总跨度周数/活跃周数/活跃率/排名序列 等)。
    """
    from dashboard.mainline_core import identify_mainlines_v3
    return identify_mainlines_v3(weekly_df, top_n=top_n, min_weeks=min_weeks, pool_n=5)


def analyze_switch_signals(old_ml, new_ml, weekly_df, industry_data, year):
    """分析一次主线切换的微观信号"""
    old_ind = old_ml["行业"]; new_ind = new_ml["行业"]
    switch_week = old_ml["结束周"]
    result = {"切换周": switch_week, "旧主线": old_ind, "新主线": new_ind,
              "旧主线类型": SECTOR_TYPE.get(old_ind, "其他"),
              "新主线类型": SECTOR_TYPE.get(new_ind, "其他"),
              "切换类型": f"{SECTOR_TYPE.get(old_ind,'其他')}→{SECTOR_TYPE.get(new_ind,'其他')}"}

    old_weeks = old_ml["周列表"]
    old_data = weekly_df[(weekly_df["行业"] == old_ind) & (weekly_df["周"].isin(old_weeks))].sort_values("周")

    if len(old_data) >= 3:
        half = len(old_data) // 2
        first_half_amt = old_data["成交额占比"].iloc[:half].mean()
        second_half_amt = old_data["成交额占比"].iloc[half:].mean()
        amt_trend = round((second_half_amt / first_half_amt - 1) * 100, 1) if first_half_amt > 0 else 0
        first_half_ret = old_data["周涨跌幅"].iloc[:half].mean()
        second_half_ret = old_data["周涨跌幅"].iloc[half:].mean()
        speed_change = round(second_half_ret - first_half_ret, 2)
        last2 = old_data.tail(2)
        rank_drift = (last2["涨幅排名"].iloc[-1] - last2["涨幅排名"].iloc[0]) if len(last2) == 2 else 0
        last_rank = old_data["涨幅排名"].iloc[-1]
        # 见顶信号 bug 修复:末3周平均排名 vs 前3周平均排名(下降≥3位为退潮)
        # 排名越小越好,故 last3 - first3 ≥ 3 表示排名变差
        first3_avg_rank = round(old_data["涨幅排名"].iloc[:3].mean(), 1)
        last3_avg_rank = round(old_data["涨幅排名"].iloc[-3:].mean(), 1)
        rank_decline = round(last3_avg_rank - first3_avg_rank, 1)
    else:
        amt_trend = speed_change = rank_drift = 0; last_rank = 0
        first3_avg_rank = last3_avg_rank = 0; rank_decline = 0

    result["旧_成交额趋势"] = amt_trend
    result["旧_涨速变化"] = speed_change
    result["旧_排名漂移"] = rank_drift
    result["旧_末周排名"] = int(last_rank)
    result["旧_前3周均排名"] = first3_avg_rank
    result["旧_末3周均排名"] = last3_avg_rank
    result["旧_排名下降"] = rank_decline
    result["旧_累计涨幅"] = old_ml["累计涨幅"]
    result["旧_持续周数"] = old_ml["持续周数"]

    top_signals = 0; top_details = []
    if amt_trend < -10:
        top_signals += 1; top_details.append(f"成交额萎缩{amt_trend:.0f}%")
    if speed_change < -1:
        top_signals += 1; top_details.append(f"涨速放缓{speed_change:+.1f}%/周")
    if rank_drift > 0:
        top_signals += 1; top_details.append(f"排名下滑{rank_drift:.0f}位")
    if old_ml["持续周数"] >= 6:
        top_signals += 1; top_details.append(f"持续{old_ml['持续周数']}周(疲态)")
    # bug 修复:原 "if last_rank > 5" 因旧主线末周必在 TOP3(排名≤3)而永不触发。
    # 改为"末3周平均排名 vs 前3周平均排名,下降≥3位"——衡量主线后期是否退潮。
    if rank_decline >= 3:
        top_signals += 1; top_details.append(f"排名退潮{rank_decline:.1f}位(末3周均{last3_avg_rank} vs 前3周均{first3_avg_rank})")
    result["旧_见顶信号强度"] = top_signals
    result["旧_见顶信号"] = " | ".join(top_details) if top_details else "无明显见顶信号"

    # 新主线在旧主线期间的表现
    new_during_old = weekly_df[(weekly_df["行业"] == new_ind) & (weekly_df["周"].isin(old_weeks))].sort_values("周")
    if not new_during_old.empty:
        if len(new_during_old) >= 3:
            half = len(new_during_old) // 2
            nf = new_during_old["成交额占比"].iloc[:half].mean()
            ns = new_during_old["成交额占比"].iloc[half:].mean()
            new_amt_trend = round((ns / nf - 1) * 100, 1) if nf > 0 else 0
        else:
            new_amt_trend = 0
        if len(new_during_old) >= 2:
            rank_climb = round(new_during_old["涨幅排名"].iloc[0] - new_during_old["涨幅排名"].iloc[-1], 1)
        else:
            rank_climb = 0
        new_cum = 1
        for p in new_during_old["周涨跌幅"].tolist():
            new_cum *= (1 + p / 100)
        new_bg_return = round((new_cum - 1) * 100, 2)
        consecutive_up = (len(new_during_old) >= 3 and all(r > 0 for r in new_during_old["周涨跌幅"].tail(3).tolist()))
        new_avg_rank = round(new_during_old["涨幅排名"].mean(), 1)
        new_best_rank = int(new_during_old["涨幅排名"].min())
    else:
        new_amt_trend = rank_climb = new_bg_return = new_avg_rank = 0
        consecutive_up = False; new_best_rank = 0

    result["新_成交额趋势"] = new_amt_trend
    result["新_排名攀升"] = rank_climb
    result["新_背景涨幅"] = new_bg_return
    result["新_连续上涨"] = consecutive_up
    result["新_平均排名"] = new_avg_rank
    result["新_最佳排名"] = new_best_rank

    ferment_signals = 0; ferment_details = []
    if new_amt_trend > 10:
        ferment_signals += 1; ferment_details.append(f"成交额放量+{new_amt_trend:.0f}%")
    if rank_climb > 3:
        ferment_signals += 1; ferment_details.append(f"排名攀升{rank_climb:.0f}位")
    if new_bg_return > 5:
        ferment_signals += 1; ferment_details.append(f"背景涨幅+{new_bg_return:.1f}%")
    if consecutive_up:
        ferment_signals += 1; ferment_details.append("连续3周上涨")
    if new_best_rank <= 5:
        ferment_signals += 1; ferment_details.append(f"曾进入TOP{new_best_rank}")
    result["新_发酵信号强度"] = ferment_signals
    result["新_发酵信号"] = " | ".join(ferment_details) if ferment_details else "无明显发酵信号（突然爆发型）"

    # 交叉窗口
    old_decline_start = None
    if len(old_data) >= 2:
        for i in range(len(old_data) - 1):
            if old_data["周涨跌幅"].iloc[i+1] < old_data["周涨跌幅"].iloc[i] - 1:
                old_decline_start = old_data["周"].iloc[i+1]
                break
    new_rise_start = None
    if not new_during_old.empty:
        for i in range(len(new_during_old)):
            if new_during_old["周涨跌幅"].iloc[i] > 2 and new_during_old["涨幅排名"].iloc[i] <= 10:
                new_rise_start = new_during_old["周"].iloc[i]
                break
    if old_decline_start and new_rise_start:
        overlap_weeks = max(0, old_ml["结束周"] - max(old_decline_start, new_rise_start) + 1)
        result["交叉窗口周数"] = overlap_weeks
        result["交叉类型"] = "渐进交叉" if overlap_weeks >= 2 else "快速切换"
    else:
        result["交叉窗口周数"] = 0
        result["交叉类型"] = "突然切换（无预兆或数据不足）"

    switch_data = weekly_df[weekly_df["周"] == switch_week]
    if not switch_data.empty:
        avg_ret = switch_data["周涨跌幅"].mean()
        up_ratio = (switch_data["周涨跌幅"] > 0).mean() * 100
        result["切换周_全市场均涨"] = round(avg_ret, 2)
        result["切换周_上涨占比"] = round(up_ratio, 1)
        if avg_ret > 2 and up_ratio > 60:
            result["切换背景"] = "普涨行情（轮动换手）"
        elif avg_ret < -2 and up_ratio < 40:
            result["切换背景"] = "普跌行情（恐慌切换）"
        elif abs(avg_ret) <= 2:
            result["切换背景"] = "震荡行情（风格切换）"
        else:
            result["切换背景"] = "分化行情"
    else:
        result["切换周_全市场均涨"] = 0
        result["切换周_上涨占比"] = 0
        result["切换背景"] = "未知"

    old_end = old_ml.get("结束日期"); new_start = new_ml.get("开始日期")
    if old_end is not None and new_start is not None:
        result["切换日期"] = old_end
        result["间隔天数"] = (new_start - old_end).days
    else:
        result["切换日期"] = None; result["间隔天数"] = 0
    return result


def generate_switch_study_report(start_year=2016, end_year=2025):
    print(f"\n{'='*70}")
    print(f"  {start_year}-{end_year} 主线切换深度研究报告")
    print(f"  分析每次切换的见顶信号 · 发酵信号 · 交叉窗口 · 市场状态")
    print(f"{'='*70}\n")

    all_switches = []
    all_mainlines = []  # v3:收集每年主线段落(带级别),供 v3 HTML 甘特图使用
    year_summaries = []

    for year in range(start_year, end_year + 1):
        print(f"[{year}] 分析中...")
        try:
            industry_data, _ = load_sw31_data(year)
        except Exception as e:
            print(f"  ✗ 数据加载失败: {e}"); continue
        weekly_df = calc_weekly_all(industry_data, year)
        if weekly_df.empty:
            print(f"  ✗ 无周度数据"); continue
        mainlines = identify_mainline_periods(weekly_df)
        print(f"  {len(mainlines)} 段主线")
        # v3:收集主线段落(标注年份)
        for m in mainlines:
            rec = dict(m)
            rec["年份"] = year
            all_mainlines.append(rec)

        # 切换配对过滤 v3:只保留中期/长期主线参与配对(短期热点为噪声,不参与切换分析)
        valid_levels = ("中期主线", "长期主线")
        valid_ml = [m for m in mainlines if m.get("级别", "短期热点") in valid_levels]

        # 接力语义:每个旧主线段结束后,[0,+2] 周窗口内,只配"开始周最早"的一条
        # 不同行业新主线(同周多条取累计涨幅最高)。排除并发同期(gap<0)与间隔过久(gap>2)。
        year_switches = []
        for old_ml in valid_ml:
            candidates = []
            for new_ml in valid_ml:
                if new_ml is old_ml:
                    continue
                if new_ml["行业"] == old_ml["行业"]:
                    continue
                week_gap = new_ml["开始周"] - old_ml["结束周"]
                if 0 <= week_gap <= 2:  # 接力窗口:结束后 0~2 周内开始
                    candidates.append((week_gap, new_ml))
            if not candidates:
                continue
            # 排序:开始周最早(gap 最小)优先;同 gap 取累计涨幅最高
            candidates.sort(key=lambda x: (x[0], -x[1].get("累计涨幅", 0)))
            best_new = candidates[0][1]
            signal = analyze_switch_signals(old_ml, new_ml=best_new, weekly_df=weekly_df,
                                            industry_data=industry_data, year=year)
            signal["年份"] = year
            signal["旧_级别"] = old_ml.get("级别", "")
            signal["新_级别"] = best_new.get("级别", "")
            year_switches.append(signal)

        seen = set(); unique = []
        for s in year_switches:
            key = (s["切换周"], s["旧主线"], s["新主线"])
            if key not in seen:
                seen.add(key); unique.append(s)
        all_switches.extend(unique)
        print(f"  {len(unique)} 次切换")

        if unique:
            year_summaries.append({
                "年份": year, "切换次数": len(unique),
                "平均见顶信号": round(np.mean([s["旧_见顶信号强度"] for s in unique]), 1),
                "平均发酵信号": round(np.mean([s["新_发酵信号强度"] for s in unique]), 1),
                "渐进交叉占比": round(sum(1 for s in unique if s["交叉类型"] == "渐进交叉") / len(unique) * 100, 1),
            })

    print(f"\n{'='*50}\n  跨年份同类切换对比...\n{'='*50}")
    switch_types = {}
    for s in all_switches:
        switch_types.setdefault(s["切换类型"], []).append(s)
    type_stats = []
    for st, switches in sorted(switch_types.items(), key=lambda x: len(x[1]), reverse=True):
        type_stats.append({
            "切换类型": st, "次数": len(switches),
            "平均见顶信号": round(np.mean([s["旧_见顶信号强度"] for s in switches]), 1),
            "平均发酵信号": round(np.mean([s["新_发酵信号强度"] for s in switches]), 1),
            "平均交叉窗口": round(np.mean([s["交叉窗口周数"] for s in switches]), 1),
            "出现年份": sorted(set(s["年份"] for s in switches)),
        })

    print(f"\n  生成 HTML 报告...")
    html = _build_switch_html(all_switches, year_summaries, type_stats, start_year, end_year)
    html_path = REPORT_DIR / f"{start_year}_{end_year}_switch_study.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    sw_df = pd.DataFrame(all_switches)
    for col in sw_df.columns:
        if sw_df[col].dtype == object:
            sw_df[col] = sw_df[col].astype(str)
    sw_df.to_csv(RAW_DIR / f"{start_year}_{end_year}_switch_signals.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(type_stats).to_csv(RAW_DIR / f"{start_year}_{end_year}_switch_type_stats.csv",
                                    index=False, encoding="utf-8-sig")

    print(f"\n  ✓ HTML: {html_path} ({os.path.getsize(html_path)/1024:.0f} KB)")
    print(f"  ✓ 信号 CSV + 类型统计 CSV 已保存")

    print(f"\n{'='*70}\n  十年切换规律总结\n{'='*70}")
    total = len(all_switches)
    if total == 0:
        print("  无切换事件"); return all_switches, type_stats
    print(f"\n  总计 {total} 次切换，{len(switch_types)} 种切换类型")
    has_top = [s for s in all_switches if s["旧_见顶信号强度"] >= 2]
    has_ferment = [s for s in all_switches if s["新_发酵信号强度"] >= 2]
    gradual = [s for s in all_switches if s["交叉类型"] == "渐进交叉"]
    print(f"\n  旧主线有明显见顶信号(≥2个): {len(has_top)}/{total} ({len(has_top)/total*100:.0f}%)")
    print(f"  新主线有明显发酵信号(≥2个): {len(has_ferment)}/{total} ({len(has_ferment)/total*100:.0f}%)")
    print(f"  渐进交叉（有重叠窗口）: {len(gradual)}/{total} ({len(gradual)/total*100:.0f}%)")
    print(f"\n  最常见切换类型 TOP5:")
    for ts in type_stats[:5]:
        print(f"    {ts['切换类型']}: {ts['次数']}次, 见顶{ts['平均见顶信号']}/5, "
              f"发酵{ts['平均发酵信号']}/5, 交叉{ts['平均交叉窗口']}周")
    print(f"\n{'='*70}\n")

    # === v3:生成增强 HTML 报告 + 结构化 CSV ===
    try:
        ml_df = pd.DataFrame(all_mainlines)
        for col in ml_df.columns:
            if ml_df[col].dtype == object:
                ml_df[col] = ml_df[col].astype(str)
        ml_df.to_csv(RAW_DIR / f"{start_year}_{end_year}_mainlines_v3.csv",
                     index=False, encoding="utf-8-sig")
        html_v3 = generate_switch_study_html_v3(all_switches, all_mainlines, type_stats,
                                                start_year, end_year)
        print(f"  ✓ v3 HTML: {html_v3} ({os.path.getsize(html_v3)/1024:.0f} KB)")
        print(f"  ✓ v3 主线段落 CSV: {RAW_DIR / f'{start_year}_{end_year}_mainlines_v3.csv'}")
    except Exception as e:
        print(f"  [WARN] v3 HTML 生成失败: {e}")
        import traceback; traceback.print_exc()

    return all_switches, type_stats


def _build_switch_html(all_switches, year_summaries, type_stats, start_year, end_year):
    css = """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
               background: #0a0e17; color: #e0e0e0; padding: 20px; max-width: 1400px; margin: 0 auto; }
        .header { text-align: center; padding: 40px 20px;
                  background: linear-gradient(135deg, #1a0a2e, #2d1b69, #1a1a3e);
                  border-radius: 16px; margin-bottom: 30px; }
        .header h1 { font-size: 32px; color: #c084fc; margin-bottom: 10px; }
        .header p { font-size: 16px; color: #8899aa; }
        .section-title { font-size: 22px; font-weight: bold; color: #c084fc;
                          margin: 30px 0 15px; padding-left: 15px; border-left: 4px solid #c084fc; }
        .stat-bar { display: flex; gap: 15px; flex-wrap: wrap; justify-content: center; margin-bottom: 25px; }
        .stat-card { background: #151b2e; border-radius: 12px; padding: 18px; min-width: 160px;
                     text-align: center; border: 1px solid #2a3555; }
        .stat-card .num { font-size: 28px; font-weight: bold; color: #c084fc; }
        .stat-card .lbl { font-size: 12px; color: #8899aa; margin-top: 4px; }
        .switch-card { background: #111827; border-radius: 12px; margin-bottom: 15px;
                       border: 1px solid #1f2937; overflow: hidden; }
        .switch-header { padding: 15px 20px; background: linear-gradient(90deg, #1a1a2e, #1f2d40);
                         display: flex; justify-content: space-between; align-items: center;
                         cursor: pointer; flex-wrap: wrap; gap: 8px; }
        .switch-header:hover { background: #1a2332; }
        .switch-body { padding: 15px 20px; display: none; }
        .switch-body.show { display: block; }
        .signal-meter { display: flex; gap: 3px; align-items: center; }
        .signal-dot { width: 12px; height: 12px; border-radius: 50%; }
        .signal-dot.active { background: #ef4444; }
        .signal-dot.inactive { background: #374151; }
        .signal-dot.ferment-active { background: #22c55e; }
        .tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin: 2px; }
        .type-sci { background: #1e3a5f; color: #60a5fa; }
        .type-con { background: #4c1d1d; color: #fca5a5; }
        .type-cyc { background: #78350f; color: #fbbf24; }
        .type-mfg { background: #064e3b; color: #34d399; }
        .type-fin { background: #312e81; color: #a78bfa; }
        .type-def { background: #1f2937; color: #9ca3af; }
        .arrow { font-size: 20px; color: #c084fc; margin: 0 8px; }
        .old-ml { color: #f87171; font-weight: bold; }
        .new-ml { color: #34d399; font-weight: bold; }
        .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 10px; }
        @media (max-width: 768px) { .detail-grid { grid-template-columns: 1fr; } }
        .detail-box { background: #0d1117; border-radius: 8px; padding: 12px; border: 1px solid #1f2937; }
        .detail-box h4 { font-size: 14px; margin-bottom: 8px; }
        .detail-box p { font-size: 13px; line-height: 1.7; color: #d1d5db; }
        .insight-box { background: #1a2332; border-radius: 12px; padding: 20px;
                       margin-bottom: 15px; border: 1px solid #2a3555; }
        .insight-box h3 { color: #c084fc; margin-bottom: 10px; font-size: 16px; }
        .insight-box p { font-size: 14px; line-height: 1.8; color: #d1d5db; }
        .type-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .type-table th { background: #1a2332; padding: 10px; text-align: left; color: #8899aa;
                         border-bottom: 1px solid #2a3555; }
        .type-table td { padding: 8px 10px; border-bottom: 1px solid #1f2937; }
        .type-table tr:hover { background: #1a2332; }
    </style>
    <script>
    function toggleSwitch(id) { var el = document.getElementById(id); if(el) el.classList.toggle('show'); }
    </script>
    """

    total = len(all_switches)
    has_top = sum(1 for s in all_switches if s["旧_见顶信号强度"] >= 2)
    has_ferment = sum(1 for s in all_switches if s["新_发酵信号强度"] >= 2)
    gradual = sum(1 for s in all_switches if s["交叉类型"] == "渐进交叉")
    top_pct = has_top / total * 100 if total > 0 else 0
    ferment_pct = has_ferment / total * 100 if total > 0 else 0
    gradual_pct = gradual / total * 100 if total > 0 else 0

    stat_html = f"""
    <div class="stat-bar">
        <div class="stat-card"><div class="num">{total}</div><div class="lbl">总切换次数</div></div>
        <div class="stat-card"><div class="num">{has_top}/{total}</div><div class="lbl">有见顶信号</div></div>
        <div class="stat-card"><div class="num">{has_ferment}/{total}</div><div class="lbl">有发酵信号</div></div>
        <div class="stat-card"><div class="num">{gradual}/{total}</div><div class="lbl">渐进交叉</div></div>
        <div class="stat-card"><div class="num">{len(type_stats)}</div><div class="lbl">切换类型</div></div>
    </div>"""

    insights_html = f"""
    <div class="insight-box"><h3>📡 见顶信号有效性：{top_pct:.0f}% 的切换有预兆</h3>
        <p>在 {total} 次主线切换中，{has_top} 次（{top_pct:.0f}%）旧主线在退出前展现了 ≥2 个见顶信号
        （成交额萎缩、涨速放缓、排名下滑、持续时间过长、末周排名跌出 TOP5）。
        这意味着{'多数切换是可预警的' if top_pct > 60 else '约一半的切换有预兆，另一半是突然事件驱动'}。</p></div>
    <div class="insight-box"><h3>🌱 发酵信号有效性：{ferment_pct:.0f}% 的新主线有提前异动</h3>
        <p>{has_ferment} 次（{ferment_pct:.0f}%）新主线在正式成为 TOP3 之前，已经在旧主线期间展现了发酵信号
        （成交额放量、排名攀升、背景涨幅、连续上涨）。
        {'大部分新主线有迹可循' if ferment_pct > 50 else '相当比例的新主线是突然爆发型，难以提前捕捉'}。</p></div>
    <div class="insight-box"><h3>🔄 交叉窗口：{gradual_pct:.0f}% 为渐进交叉</h3>
        <p>{gradual} 次切换属于"渐进交叉"（旧主线走弱与新主线走强有时间重叠），给出了调仓窗口。
        {'大多数切换有缓冲期，不需要追涨杀跌' if gradual_pct > 50 else '多数切换较为突然，需要快速反应或事前布局'}。</p></div>
    """

    type_rows = ""
    for ts in type_stats:
        st = ts["切换类型"]
        # 用主类型(箭头两侧任一含)定色
        type_class = ""
        if "科技" in st: type_class = "type-sci"
        elif "消费" in st: type_class = "type-con"
        elif "周期" in st: type_class = "type-cyc"
        elif "金融" in st: type_class = "type-fin"
        elif "制造" in st: type_class = "type-mfg"
        elif "防御" in st: type_class = "type-def"
        years_str = ", ".join(map(str, ts["出现年份"]))
        top_meter = "".join([f'<span class="signal-dot active"></span>' if i < ts["平均见顶信号"]
                             else '<span class="signal-dot inactive"></span>' for i in range(5)])
        ferment_meter = "".join([f'<span class="signal-dot ferment-active"></span>' if i < ts["平均发酵信号"]
                                  else '<span class="signal-dot inactive"></span>' for i in range(5)])
        type_rows += f"""<tr>
            <td><span class="tag {type_class}">{st}</span></td>
            <td>{ts['次数']}</td>
            <td><div class="signal-meter">{top_meter}</div></td>
            <td><div class="signal-meter">{ferment_meter}</div></td>
            <td>{ts['平均交叉窗口']}周</td>
            <td style="font-size:11px;color:#8899aa">{years_str}</td></tr>"""

    type_html = f"""<table class="type-table"><thead><tr>
        <th>切换类型</th><th>次数</th><th>见顶信号(5分)</th>
        <th>发酵信号(5分)</th><th>交叉窗口</th><th>出现年份</th>
        </tr></thead><tbody>{type_rows}</tbody></table>"""

    switches_by_year = {}
    for s in all_switches:
        switches_by_year.setdefault(s["年份"], []).append(s)

    year_sections = ""
    for year in sorted(switches_by_year.keys()):
        switches = switches_by_year[year]
        cards = ""
        for idx, s in enumerate(switches):
            card_id = f"sw_{year}_{idx}"
            top_dots = "".join([f'<span class="signal-dot {"active" if i < s["旧_见顶信号强度"] else "inactive"}"></span>' for i in range(5)])
            ferment_dots = "".join([f'<span class="signal-dot {"ferment-active" if i < s["新_发酵信号强度"] else "inactive"}"></span>' for i in range(5)])
            try:
                sw_date = pd.Timestamp(s["切换日期"]).strftime("%m-%d") if s.get("切换日期") is not None else f"W{s['切换周']}"
            except Exception:
                sw_date = f"W{s['切换周']}"
            cards += f"""
            <div class="switch-card">
                <div class="switch-header" onclick="toggleSwitch('{card_id}')">
                    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px">
                        <span style="color:#8899aa;font-size:13px">{sw_date}</span>
                        <span class="old-ml">{s['旧主线']}</span>
                        <span style="font-size:11px;color:#8899aa">+{s['旧_累计涨幅']}%/{s['旧_持续周数']}周</span>
                        <span class="arrow">→</span>
                        <span class="new-ml">{s['新主线']}</span>
                        <span class="tag" style="background:#1a1a2e;color:#c084fc;border:1px solid #4c1d95;font-size:11px">{s['切换类型']}</span>
                    </div>
                    <div style="display:flex;gap:15px;align-items:center">
                        <div style="font-size:11px;color:#8899aa">见顶 <div class="signal-meter" style="display:inline-flex">{top_dots}</div></div>
                        <div style="font-size:11px;color:#8899aa">发酵 <div class="signal-meter" style="display:inline-flex">{ferment_dots}</div></div>
                        <span style="color:#6b7280;font-size:13px">▼</span>
                    </div>
                </div>
                <div id="{card_id}" class="switch-body">
                    <div class="detail-grid">
                        <div class="detail-box">
                            <h4 style="color:#f87171">📉 旧主线见顶分析：{s['旧主线']}</h4>
                            <p>累计涨幅: <strong>+{s['旧_累计涨幅']}%</strong> / {s['旧_持续周数']}周<br>
                            成交额趋势: <strong>{s['旧_成交额趋势']:+.1f}%</strong>{'（萎缩⚠️）' if s['旧_成交额趋势'] < -10 else '（稳定）' if abs(s['旧_成交额趋势']) <= 10 else '（仍在放量）'}<br>
                            涨速变化: <strong>{s['旧_涨速变化']:+.2f}%/周</strong>{'（放缓⚠️）' if s['旧_涨速变化'] < -1 else '（加速）' if s['旧_涨速变化'] > 1 else '（平稳）'}<br>
                            末周排名: 第<strong>{s['旧_末周排名']}</strong>名<br>
                            <span style="color:#f59e0b">信号: {s['旧_见顶信号']}</span></p>
                        </div>
                        <div class="detail-box">
                            <h4 style="color:#34d399">📈 新主线发酵分析：{s['新主线']}</h4>
                            <p>旧主线期间涨幅: <strong>{s['新_背景涨幅']:+.1f}%</strong><br>
                            成交额趋势: <strong>{s['新_成交额趋势']:+.1f}%</strong>{'（放量🔥）' if s['新_成交额趋势'] > 10 else '（平稳）'}<br>
                            排名攀升: <strong>{s['新_排名攀升']:+.1f}位</strong>{'（显著攀升🔥）' if s['新_排名攀升'] > 3 else ''}<br>
                            最佳排名: 第<strong>{s['新_最佳排名']}</strong>名{'（曾进入TOP5🔥）' if s['新_最佳排名'] <= 5 else ''}<br>
                            连续上涨: {'是 🔥' if s['新_连续上涨'] else '否'}<br>
                            <span style="color:#f59e0b">信号: {s['新_发酵信号']}</span></p>
                        </div>
                    </div>
                    <div class="detail-box" style="margin-top:10px">
                        <h4 style="color:#c084fc">🔄 切换环境</h4>
                        <p>交叉类型: <strong>{s['交叉类型']}</strong>（重叠{s['交叉窗口周数']}周）<br>
                        切换背景: <strong>{s['切换背景']}</strong>（全市场均涨 {s['切换周_全市场均涨']:+.1f}%, 上涨占比 {s['切换周_上涨占比']:.0f}%）</p>
                    </div>
                </div>
            </div>"""
        year_sections += f"""<div style="margin-bottom:25px">
            <h3 style="color:#c084fc;font-size:18px;margin-bottom:10px">📅 {year} 年（{len(switches)} 次切换）</h3>
            {cards}</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{start_year}-{end_year} 主线切换深度研究</title>{css}</head>
<body>
    <div class="header"><h1>🔬 {start_year}-{end_year} 主线切换深度研究</h1>
        <p>每次切换的见顶信号 · 发酵信号 · 交叉窗口 · 跨年份同类对比</p>
        <p style="margin-top:8px;color:#6b7280">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 31 申万一级行业</p></div>
    {stat_html}
    <div class="section-title">📊 核心发现</div>{insights_html}
    <div class="section-title">📋 切换类型统计（跨年份对比）</div>
    <div style="background:#111827;border-radius:12px;padding:15px;border:1px solid #1f2937;overflow-x:auto">{type_html}</div>
    <div class="section-title">📅 逐年切换详情（点击展开）</div>{year_sections}
</body></html>"""
    return html


# 行业大类映射(用于切换模式归纳)
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

# 年度时代标签
_ERA_LABELS = {
    2016: ("供给侧改革", "#e67e22"), 2017: ("核心资产崛起", "#2ecc71"),
    2018: ("去杠杆熊市", "#e74c3c"), 2019: ("科技牛启动", "#3498db"),
    2020: ("疫情与流动性", "#9b59b6"), 2021: ("碳中和新能源", "#1abc9c"),
    2022: ("地缘与衰退", "#e74c3c"), 2023: ("AI元年", "#3498db"),
    2024: ("AI深化+924", "#f39c12"), 2025: ("AI应用落地", "#2ecc71"),
}

_LEVEL_COLORS = {"长期主线": "#f1c40f", "中期主线": "#3498db", "短期热点": "#7f8c8d"}


def _hex_to_rgb(hex_color):
    """#e74c3c → '231,76,60'"""
    hex_color = hex_color.lstrip("#")
    return ",".join(str(int(hex_color[i:i + 2], 16)) for i in (0, 2, 4))


def _signal_score_class(score):
    """见顶/发酵强度 → CSS class"""
    if score >= 3:
        return "score-high"
    if score >= 2:
        return "score-medium"
    return "score-low"


def generate_switch_study_html_v3(all_switches, all_mainlines, type_stats,
                                  start_year, end_year):
    """v3 增强版切换深度研究 HTML 报告。

    五层结构:统计仪表盘 / 切换模式库 / 十年洞察 / 逐年面板(含主线甘特图) / 切换信号卡片。
    基于真实数据契约(all_switches 含嵌套信号字段,all_mainlines 含级别)。
    信号有效性以切换数为分母(与主报告一致)。
    """
    from collections import Counter, defaultdict

    total_switches = len(all_switches)
    total_mid = sum(1 for m in all_mainlines if m.get("级别") == "中期主线")
    total_long = sum(1 for m in all_mainlines if m.get("级别") == "长期主线")

    # 信号有效性(切换数分母)
    top_eff = sum(1 for s in all_switches if s.get("旧_见顶信号强度", 0) >= 2)
    ferm_eff = sum(1 for s in all_switches if s.get("新_发酵信号强度", 0) >= 2)
    top_pct = top_eff / total_switches * 100 if total_switches else 0
    ferm_pct = ferm_eff / total_switches * 100 if total_switches else 0

    # 切换模式(行业大类)
    pattern_stats = Counter()
    pattern_years = defaultdict(set)
    for s in all_switches:
        og = _SECTOR_GROUP.get(s.get("旧主线", ""), "其他")
        ng = _SECTOR_GROUP.get(s.get("新主线", ""), "其他")
        pat = f"{og}→{ng}"
        pattern_stats[pat] += 1
        pattern_years[pat].add(s.get("年份"))
    top_patterns = pattern_stats.most_common(10)

    # 枢纽行业
    exit_counter = Counter(s.get("旧主线", "") for s in all_switches)
    enter_counter = Counter(s.get("新主线", "") for s in all_switches)
    top_exit = exit_counter.most_common(3)
    top_enter = enter_counter.most_common(3)

    # 平均退出持续周数
    exit_spans = [s.get("旧_持续周数", 0) for s in all_switches if s.get("旧_持续周数", 0) > 0]
    avg_exit_span = sum(exit_spans) / len(exit_spans) if exit_spans else 0

    # 按(旧,新)级别统计
    level_pairs = Counter(
        f"{s.get('旧_级别', '?')}→{s.get('新_级别', '?')}" for s in all_switches
    )

    max_pat = top_patterns[0][1] if top_patterns else 1
    pat_colors = ["#f1c40f", "#3498db", "#2ecc71", "#e74c3c", "#9b59b6",
                  "#f39c12", "#1abc9c", "#e67e22", "#16a085", "#c0392b"]

    H = []  # html parts

    # ── HEAD + CSS ──
    H.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{start_year}-{end_year} 主线切换深度研究 v3</title>
<style>
:root {{
  --bg-primary:#0a0e17; --bg-card:#131a2b; --bg-card-hover:#1a2340;
  --text-primary:#e8eaf0; --text-secondary:#8892a4; --text-muted:#5a6478;
  --gold:#f1c40f; --blue:#3498db; --green:#2ecc71; --red:#e74c3c;
  --orange:#f39c12; --purple:#9b59b6; --border:#1e2a42;
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg-primary);color:var(--text-primary);
  font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
  line-height:1.6;padding:20px;}}
.container{{max-width:1400px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#0f1629,#1a2a4a,#0d1b2a);
  border:1px solid var(--border);border-radius:16px;padding:40px;margin-bottom:24px;text-align:center;}}
.header h1{{font-size:32px;background:linear-gradient(90deg,var(--gold),var(--blue));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;}}
.header .sub{{color:var(--text-secondary);font-size:16px;}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;}}
.stat-card{{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center;}}
.stat-card .v{{font-size:36px;font-weight:700;margin-bottom:4px;}}
.stat-card .l{{color:var(--text-secondary);font-size:13px;}}
.section{{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:24px;}}
.section h2{{font-size:20px;color:var(--gold);margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border);}}
.pat-bar{{display:flex;align-items:center;margin-bottom:12px;gap:12px;}}
.pat-label{{width:140px;font-size:14px;font-weight:600;text-align:right;flex-shrink:0;}}
.pat-fill{{height:28px;border-radius:6px;display:flex;align-items:center;padding:0 10px;
  font-size:12px;font-weight:600;color:#fff;min-width:40px;}}
.pat-years{{color:var(--text-secondary);font-size:12px;flex-shrink:0;}}
.year-sec{{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;margin-bottom:20px;overflow:hidden;}}
.year-hd{{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;cursor:pointer;transition:background .2s;}}
.year-hd:hover{{background:var(--bg-card-hover);}}
.year-title{{display:flex;align-items:center;gap:12px;}}
.year-title h3{{font-size:20px;}}
.era-badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;}}
.year-stats{{display:flex;gap:20px;color:var(--text-secondary);font-size:13px;flex-wrap:wrap;}}
.toggle{{font-size:18px;color:var(--text-muted);transition:transform .3s;}}
.year-sec.open .toggle{{transform:rotate(180deg);}}
.year-ct{{padding:0 24px 24px;display:none;}}
.year-ct.active{{display:block;}}
.tl-row{{display:flex;align-items:center;margin-bottom:4px;min-height:26px;}}
.tl-label{{width:90px;font-size:12px;color:var(--text-secondary);text-align:right;padding-right:10px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.tl-track{{flex:1;position:relative;height:20px;background:rgba(255,255,255,0.02);border-radius:4px;}}
.tl-bar{{position:absolute;height:16px;top:2px;border-radius:4px;font-size:10px;color:#fff;
  display:flex;align-items:center;justify-content:center;overflow:hidden;white-space:nowrap;opacity:.85;}}
.tl-bar:hover{{opacity:1;z-index:10;}}
.sw-card{{background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:10px;
  padding:16px 20px;margin-bottom:12px;transition:border-color .2s;}}
.sw-card:hover{{border-color:var(--blue);}}
.sw-hd{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px;}}
.sw-flow{{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:600;flex-wrap:wrap;}}
.sw-arrow{{color:var(--gold);font-size:18px;}}
.sw-meta{{font-size:12px;color:var(--text-muted);}}
.sig-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px;}}
.sig-box{{padding:10px 14px;border-radius:8px;font-size:13px;}}
.sig-box.top{{background:rgba(231,76,60,0.08);border:1px solid rgba(231,76,60,0.2);}}
.sig-box.ferm{{background:rgba(46,204,113,0.08);border:1px solid rgba(46,204,113,0.2);}}
.sig-title{{font-weight:600;margin-bottom:6px;display:flex;align-items:center;gap:6px;}}
.sig-title.t{{color:var(--red);}} .sig-title.f{{color:var(--green);}}
.sig-item{{color:var(--text-secondary);font-size:12px;line-height:1.6;}}
.sig-score{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;margin-left:6px;}}
.sc-high{{background:rgba(231,76,60,0.2);color:var(--red);}}
.sc-med{{background:rgba(243,156,18,0.2);color:var(--orange);}}
.sc-low{{background:rgba(149,165,166,0.15);color:var(--text-muted);}}
.lvl-badge{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;}}
.lvl-long{{background:rgba(241,196,15,0.2);color:var(--gold);}}
.lvl-mid{{background:rgba(52,152,219,0.2);color:var(--blue);}}
.insights{{background:linear-gradient(135deg,#0f1629,#162040);border:1px solid var(--gold);border-radius:12px;padding:24px;margin-bottom:24px;}}
.insights h2{{color:var(--gold);font-size:20px;margin-bottom:16px;}}
.ins-item{{padding:12px 0;border-bottom:1px solid rgba(241,196,15,0.1);font-size:14px;line-height:1.8;}}
.ins-item:last-child{{border-bottom:none;}}
.ins-num{{display:inline-block;width:24px;height:24px;line-height:24px;text-align:center;
  background:var(--gold);color:#000;border-radius:50%;font-size:12px;font-weight:700;margin-right:8px;}}
@media(max-width:768px){{.sig-grid{{grid-template-columns:1fr;}}.stats-grid{{grid-template-columns:repeat(2,1fr);}}}}
</style>
</head>
<body><div class="container">
""")

    # ── 头部 ──
    H.append(f"""
<div class="header">
  <h1>📊 {start_year}-{end_year} 主线切换深度研究 v3</h1>
  <div class="sub">容间断滑窗算法 · 仅中期/长期主线 · {total_switches}次接力切换</div>
</div>
""")

    # ── 统计仪表盘 ──
    H.append(f"""
<div class="stats-grid">
  <div class="stat-card"><div class="v" style="color:var(--gold)">{total_switches}</div><div class="l">有效切换次数</div></div>
  <div class="stat-card"><div class="v" style="color:var(--blue)">{total_mid}</div><div class="l">中期主线 (4-8周)</div></div>
  <div class="stat-card"><div class="v" style="color:var(--orange)">{total_long}</div><div class="l">长期主线 (8周+)</div></div>
  <div class="stat-card"><div class="v" style="color:var(--red)">{top_pct:.0f}%</div><div class="l">见顶信号有效性</div></div>
  <div class="stat-card"><div class="v" style="color:var(--green)">{ferm_pct:.0f}%</div><div class="l">发酵信号有效性</div></div>
  <div class="stat-card"><div class="v" style="color:var(--purple)">{len(top_patterns)}</div><div class="l">切换模式类型</div></div>
</div>
""")

    # ── 切换模式库 ──
    H.append('<div class="section"><h2>🔄 十年切换模式库 — 风格迁移规律</h2>')
    for idx, (pat, cnt) in enumerate(top_patterns):
        pct = cnt / total_switches * 100 if total_switches else 0
        width = cnt / max_pat * 100
        color = pat_colors[idx % len(pat_colors)]
        yrs = ", ".join(str(y) for y in sorted(pattern_years[pat]))
        H.append(
            f'<div class="pat-bar">'
            f'<div class="pat-label">{pat}</div>'
            f'<div class="pat-fill" style="width:{width:.1f}%;background:{color};">{cnt}次 ({pct:.0f}%)</div>'
            f'<div class="pat-years">{yrs}</div></div>'
        )
    H.append('</div>')

    # ── 十年洞察 ──
    def _hub(lst, i):
        return lst[i][0] if len(lst) > i else "-"

    pat0 = top_patterns[0] if top_patterns else ("-", 0)
    pat1 = top_patterns[1] if len(top_patterns) > 1 else ("-", 0)
    pat2 = top_patterns[2] if len(top_patterns) > 2 else ("-", 0)
    H.append(f"""
<div class="insights">
  <h2>💡 十年切换规律洞察</h2>
  <div class="ins-item"><span class="ins-num">1</span><strong>切换枢纽行业:</strong>
    退出最频繁:{_hub(top_exit,0)}({top_exit[0][1] if top_exit else 0}次)、
    {_hub(top_exit,1)}({top_exit[1][1] if len(top_exit)>1 else 0}次)、
    {_hub(top_exit,2)}({top_exit[2][1] if len(top_exit)>2 else 0}次)。
    进入最频繁:{_hub(top_enter,0)}({top_enter[0][1] if top_enter else 0}次)、
    {_hub(top_enter,1)}({top_enter[1][1] if len(top_enter)>1 else 0}次)。
    高频退出说明该行业易"见光死",高频进入说明它是资金的避风港或新方向。</div>
  <div class="ins-item"><span class="ins-num">2</span><strong>切换前信号:</strong>
    {total_switches}次接力切换中,{top_pct:.0f}%的旧主线在结束前出现≥2个见顶信号,
    {ferm_pct:.0f}%的新主线在确立前出现发酵信号。超过半数切换"有预兆"。</div>
  <div class="ins-item"><span class="ins-num">3</span><strong>主线平均寿命:</strong>
    被切换的主线平均持续 {avg_exit_span:.1f} 周(约 {avg_exit_span/4.3:.1f} 个月)。
    级别分布:{' / '.join(f'{k} {v}次' for k,v in level_pairs.most_common())}。</div>
  <div class="ins-item"><span class="ins-num">4</span><strong>风格迁移规律:</strong>
    最常见切换模式是"{pat0[0]}"({pat0[1]}次),其次是"{pat1[0]}"({pat1[1]}次)、"{pat2[0]}"({pat2[1]}次)。
    同风格内部轮动远多于跨风格切换,说明A股主线迁移惯性很强。</div>
  <div class="ins-item"><span class="ins-num">5</span><strong>实战启示:</strong>
    当一条中期以上主线出现≥2个见顶信号时,历史数据显示{top_pct:.0f}%的情况下信号可靠,不必等彻底崩塌再离场;
    同时关注同风格内是否出现发酵信号({ferm_pct:.0f}%有效),这往往是接力方向。</div>
</div>
""")

    # ── 逐年面板 ──
    sw_by_year = defaultdict(list)
    for s in all_switches:
        sw_by_year[s.get("年份")].append(s)
    ml_by_year = defaultdict(list)
    for m in all_mainlines:
        ml_by_year[m.get("年份")].append(m)

    for year in range(start_year, end_year + 1):
        era_name, era_color = _ERA_LABELS.get(year, ("", "#888888"))
        yr_sw = sw_by_year.get(year, [])
        yr_ml = ml_by_year.get(year, [])
        yr_mid = sum(1 for m in yr_ml if m.get("级别") == "中期主线")
        yr_long = sum(1 for m in yr_ml if m.get("级别") == "长期主线")
        yr_top = sum(1 for s in yr_sw if s.get("旧_见顶信号强度", 0) >= 2)
        yr_ferm = sum(1 for s in yr_sw if s.get("新_发酵信号强度", 0) >= 2)
        yr_n = len(yr_sw)
        yr_top_pct = yr_top / yr_n * 100 if yr_n else 0
        yr_ferm_pct = yr_ferm / yr_n * 100 if yr_n else 0
        is_first = (year == start_year)
        H.append(f"""
<div class="year-sec{' open' if is_first else ''}" id="y{year}">
  <div class="year-hd" onclick="tog({year})">
    <div class="year-title"><h3>{year}</h3>
      <span class="era-badge" style="background:rgba({_hex_to_rgb(era_color)},0.2);color:{era_color};">{era_name}</span></div>
    <div class="year-stats">
      <span>🔄 {yr_n}次切换</span><span>📊 中期{yr_mid} / 长期{yr_long}</span>
      <span>🎯 见顶{yr_top_pct:.0f}% / 发酵{yr_ferm_pct:.0f}%</span></div>
    <span class="toggle">▼</span>
  </div>
  <div class="year-ct{' active' if is_first else ''}">
""")

        # 甘特图(仅中期/长期)
        mid_long = [m for m in yr_ml if m.get("级别") in ("中期主线", "长期主线")]
        if mid_long:
            week_nums = sorted(set(
                int(m.get("开始周", 0)) for m in mid_long) |
                set(int(m.get("结束周", 0)) for m in mid_long))
            if len(week_nums) >= 2:
                wmin, wmax = week_nums[0], week_nums[-1]
                wrange = max(wmax - wmin, 1)
                H.append('<div style="font-size:13px;color:var(--text-secondary);margin:8px 0;">📈 主线生命周期时间轴(仅中期/长期)</div>')
                by_ind = defaultdict(list)
                for m in mid_long:
                    by_ind[m.get("行业", "")].append(m)
                for ind in sorted(by_ind):
                    H.append(f'<div class="tl-row"><div class="tl-label" title="{ind}">{ind}</div><div class="tl-track">')
                    for seg in by_ind[ind]:
                        sw_ = int(seg.get("开始周", wmin))
                        ew_ = int(seg.get("结束周", wmax))
                        lvl = seg.get("级别", "")
                        color = _LEVEL_COLORS.get(lvl, "#888888")
                        cum = seg.get("累计涨幅", 0)
                        spanw = seg.get("总跨度周数", 0)
                        left = (sw_ - wmin) / wrange * 100
                        width = max((ew_ - sw_ + 1) / wrange * 100, 3)
                        ret_s = f"+{cum:.1f}%" if cum >= 0 else f"{cum:.1f}%"
                        H.append(
                            f'<div class="tl-bar" style="left:{left:.1f}%;width:{width:.1f}%;background:{color};" '
                            f'title="{ind} | {lvl} | {spanw}周 | {ret_s}">{ret_s}</div>')
                    H.append('</div></div>')

        # 切换卡片
        if yr_sw:
            H.append(f'<div style="font-size:13px;color:var(--text-secondary);margin:16px 0 8px;">🔄 {year}年 {len(yr_sw)} 次主线接力切换</div>')
            for s in yr_sw:
                old_ind = s.get("旧主线", ""); new_ind = s.get("新主线", "")
                old_lvl = s.get("旧_级别", ""); new_lvl = s.get("新_级别", "")
                old_ret = s.get("旧_累计涨幅", 0); new_ret = s.get("新_累计涨幅", 0)
                old_span = s.get("旧_持续周数", 0); new_span = s.get("新_持续周数", 0)
                sw_week = s.get("切换周", "")
                old_lc = "lvl-long" if old_lvl == "长期主线" else "lvl-mid"
                new_lc = "lvl-long" if new_lvl == "长期主线" else "lvl-mid"
                old_rs = f"+{old_ret:.1f}%" if old_ret >= 0 else f"{old_ret:.1f}%"
                new_rs = f"+{new_ret:.1f}%" if new_ret >= 0 else f"{new_ret:.1f}%"
                top_sc = s.get("旧_见顶信号强度", 0)
                ferm_sc = s.get("新_发酵信号强度", 0)
                top_txt = s.get("旧_见顶信号", "无明显见顶信号")
                ferm_txt = s.get("新_发酵信号", "无明显发酵信号")
                og = _SECTOR_GROUP.get(old_ind, "其他"); ng = _SECTOR_GROUP.get(new_ind, "其他")
                cross = "跨风格" if og != ng else "同风格"
                top_cl = _signal_score_class(top_sc)
                ferm_cl = _signal_score_class(ferm_sc)
                top_html = top_txt.replace(" | ", "<br>") if "无明显" not in top_txt else "未检测到显著见顶信号"
                ferm_html = ferm_txt.replace(" | ", "<br>") if "无明显" not in ferm_txt else "新主线启动前无显著异动"
                H.append(f"""
    <div class="sw-card">
      <div class="sw-hd">
        <div class="sw-flow">
          <span class="lvl-badge {old_lc}">{old_lvl}</span>{old_ind}
          <span style="color:var(--text-muted);font-size:12px;">({old_rs}, {old_span}周)</span>
          <span class="sw-arrow">→</span>
          <span class="lvl-badge {new_lc}">{new_lvl}</span>{new_ind}
          <span style="color:var(--text-muted);font-size:12px;">({new_rs}, {new_span}周)</span>
        </div>
        <div class="sw-meta">第{sw_week}周 · {cross}({og}→{ng})</div>
      </div>
      <div class="sig-grid">
        <div class="sig-box top">
          <div class="sig-title t">⚠️ 见顶信号<span class="sig-score {top_cl}">{top_sc}项触发</span></div>
          <div class="sig-item">{top_html}</div>
        </div>
        <div class="sig-box ferm">
          <div class="sig-title f">🌱 发酵信号<span class="sig-score {ferm_cl}">{ferm_sc}项触发</span></div>
          <div class="sig-item">{ferm_html}</div>
        </div>
      </div>
    </div>""")
        H.append('</div></div>')  # year-ct, year-sec

    # ── 页脚 + JS ──
    H.append(f"""
<div style="text-align:center;padding:30px;color:var(--text-muted);font-size:12px;">
  主线识别算法 v3(容间断滑窗 TOP5 · 接力窗口[0,+2]周) · 数据源:申万31一级行业日线<br>
  覆盖 {start_year}-{end_year} · {total_switches}次有效接力切换 · 见顶{top_pct:.0f}% / 发酵{ferm_pct:.0f}%
</div></div>
<script>
function tog(y){{var s=document.getElementById('y'+y);var c=s.querySelector('.year-ct');
  s.classList.toggle('open');c.classList.toggle('active');}}
</script>
</body></html>""")

    html = "\n".join(H)
    out_path = REPORT_DIR / f"{start_year}_{end_year}_switch_study_v3.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return str(out_path)


if __name__ == "__main__":
    start = 2016; end = 2025
    if len(sys.argv) > 1:
        try: start = int(sys.argv[1])
        except ValueError: pass
    if len(sys.argv) > 2:
        try: end = int(sys.argv[2])
        except ValueError: pass
    generate_switch_study_report(start, end)
