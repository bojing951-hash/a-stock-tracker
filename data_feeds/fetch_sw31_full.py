#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_sw31_full.py
拉取申万一级31个行业指数的完整日线数据（2015-01-05 ~ 今天）
数据源优先级：
  A) ak.index_hist_sw (申万宏源官网，字段最全)
  B) ak.sw_index_daily (申万宏源，字段略少)
  C) ak.index_zh_a_hist (东方财富，兜底)

输出：
  raw_data/sw31_daily/{行业名称}.csv  （31个单行业文件）
  raw_data/sw31_daily_all.csv         （合并全量表）
"""

import os
import sys
import time
import datetime
import warnings
import traceback

import pandas as pd

warnings.filterwarnings("ignore")

# ── 清除代理（本环境代理7890返回502，直连可用）──
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(k, None)

import akshare as ak

# ===== 31个申万一级行业（2021版）=====
SW31_INDUSTRIES = {
    "801010": "农林牧渔",
    "801030": "基础化工",
    "801040": "钢铁",
    "801050": "有色金属",
    "801080": "电子",
    "801110": "家用电器",
    "801120": "食品饮料",
    "801130": "纺织服饰",
    "801140": "轻工制造",
    "801150": "医药生物",
    "801160": "公用事业",
    "801170": "交通运输",
    "801180": "房地产",
    "801200": "商贸零售",
    "801210": "社会服务",
    "801230": "综合",
    "801710": "建筑材料",
    "801720": "建筑装饰",
    "801730": "电力设备",
    "801740": "国防军工",
    "801750": "计算机",
    "801760": "传媒",
    "801770": "通信",
    "801780": "银行",
    "801790": "非银金融",
    "801880": "汽车",
    "801890": "机械设备",
    "801950": "煤炭",
    "801960": "石油石化",
    "801970": "环保",
    "801980": "美容护理",
}

OLD_TO_NEW_NOTE = """
注意：以下4个行业代码是2021年新设，2021年之前无数据：
  801950 煤炭    ← 旧版"采掘"(801020)拆分
  801960 石油石化 ← 旧版"采掘"(801020)+"化工"(801030)拆分
  801970 环保    ← 旧版"公用事业"(801160)拆分
  801980 美容护理 ← 新增行业
旧版更名：
  电气设备 → 电力设备(801730)
  休闲服务 → 社会服务(801210)
  纺织服装 → 纺织服饰(801130)
  商业贸易 → 商贸零售(801200)
"""

START_DATE = "20150101"
END_DATE = datetime.datetime.now().strftime("%Y%m%d")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def fetch_method_a(code, name):
    """方案A: ak.index_hist_sw — 字段最全（申万宏源官网）"""
    try:
        df = ak.index_hist_sw(symbol=code, period="day")
        if df is None or df.empty:
            return None, "empty"
        col_map = {}
        for col in df.columns:
            cl = str(col).strip()
            if "日期" in cl or "发布" in cl or "date" in cl.lower():
                col_map[col] = "日期"
            elif cl == "开盘指数" or cl == "开盘":
                col_map[col] = "开盘"
            elif cl == "收盘指数" or cl == "收盘":
                col_map[col] = "收盘"
            elif cl == "最高指数" or cl == "最高":
                col_map[col] = "最高"
            elif cl == "最低指数" or cl == "最低":
                col_map[col] = "最低"
            elif "成交量" in cl:
                col_map[col] = "成交量_亿股"
            elif "成交额占比" in cl:
                col_map[col] = "成交额占比_pct"
            elif "成交额" in cl:
                col_map[col] = "成交额_亿元"
            elif "涨跌幅" in cl:
                col_map[col] = "涨跌幅_pct"
            elif "换手率" in cl:
                col_map[col] = "换手率_pct"
            elif "市盈率" in cl:
                col_map[col] = "市盈率"
            elif "市净率" in cl:
                col_map[col] = "市净率"
            elif "流通市值" in cl:
                col_map[col] = "流通市值_亿元"
            elif "均价" in cl:
                col_map[col] = "均价"
            elif "股息率" in cl:
                col_map[col] = "股息率_pct"
            elif "指数代码" in cl or cl == "代码":
                col_map[col] = "行业代码"
            elif "指数名称" in cl:
                col_map[col] = "行业名称"
        df = df.rename(columns=col_map)
        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            df = df.dropna(subset=["日期"])
            df = df[df["日期"] >= "2015-01-01"].copy()
            df = df.sort_values("日期").reset_index(drop=True)
        if df.empty:
            return None, "no_data_after_2015"
        df["行业代码"] = code
        df["行业名称"] = name
        return df, "ok"
    except Exception as e:
        return None, str(e)[:120]


def fetch_method_b(code, name):
    """方案B: ak.sw_index_daily"""
    try:
        df = ak.sw_index_daily(symbol=code, start_date=START_DATE, end_date=END_DATE)
        if df is None or df.empty:
            return None, "empty"
        col_map = {}
        for col in df.columns:
            cl = str(col).strip().lower()
            if cl in ("date", "日期"):
                col_map[col] = "日期"
            elif cl in ("open", "开盘"):
                col_map[col] = "开盘"
            elif cl in ("close", "收盘"):
                col_map[col] = "收盘"
            elif cl in ("high", "最高"):
                col_map[col] = "最高"
            elif cl in ("low", "最低"):
                col_map[col] = "最低"
            elif cl in ("volume", "成交量"):
                col_map[col] = "成交量_亿股"
            elif cl in ("amount", "成交额"):
                col_map[col] = "成交额_亿元"
        df = df.rename(columns=col_map)
        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            df = df.dropna(subset=["日期"])
            df = df[df["日期"] >= "2015-01-01"].copy()
            df = df.sort_values("日期").reset_index(drop=True)
        if df.empty:
            return None, "no_data_after_2015"
        df["行业代码"] = code
        df["行业名称"] = name
        return df, "ok"
    except Exception as e:
        return None, str(e)[:120]


def fetch_method_c(code, name):
    """方案C: ak.index_zh_a_hist (东方财富兜底)"""
    try:
        df = ak.index_zh_a_hist(symbol=code, period="daily",
                                start_date=START_DATE, end_date=END_DATE)
        if df is None or df.empty:
            return None, "empty"
        col_map = {}
        for col in df.columns:
            cl = str(col).strip()
            if cl == "日期":
                col_map[col] = "日期"
            elif cl == "开盘":
                col_map[col] = "开盘"
            elif cl == "收盘":
                col_map[col] = "收盘"
            elif cl == "最高":
                col_map[col] = "最高"
            elif cl == "最低":
                col_map[col] = "最低"
            elif cl == "成交量":
                col_map[col] = "成交量_亿股"
            elif cl == "成交额":
                col_map[col] = "成交额_亿元"
            elif cl == "涨跌幅":
                col_map[col] = "涨跌幅_pct"
            elif cl == "振幅":
                col_map[col] = "振幅_pct"
            elif cl == "换手率":
                col_map[col] = "换手率_pct"
        df = df.rename(columns=col_map)
        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            df = df.dropna(subset=["日期"])
            df = df.sort_values("日期").reset_index(drop=True)
        if df.empty:
            return None, "no_data_after_2015"
        df["行业代码"] = code
        df["行业名称"] = name
        return df, "ok"
    except Exception as e:
        return None, str(e)[:120]


def fetch_industry(code, name):
    methods = [
        ("A_index_hist_sw", fetch_method_a),
        ("B_sw_index_daily", fetch_method_b),
        ("C_index_zh_a_hist", fetch_method_c),
    ]
    status = "unknown"
    for method_name, func in methods:
        df, status = func(code, name)
        if df is not None and not df.empty:
            return df, method_name, status
        time.sleep(0.5)
    return None, "ALL_FAILED", status


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(project_root, "raw_data", "sw31_daily")
    ensure_dir(output_dir)

    print("=" * 70)
    print(f"  申万一级31行业 全量日线数据拉取")
    print(f"  日期范围: {START_DATE} ~ {END_DATE}")
    print(f"  输出目录: {output_dir}")
    print(f"  AKShare版本: {ak.__version__}")
    print("=" * 70)
    print(OLD_TO_NEW_NOTE)

    results = []
    all_dfs = []
    success_count = 0
    fail_count = 0

    for i, (code, name) in enumerate(SW31_INDUSTRIES.items(), 1):
        print(f"[{i:02d}/31] {name} ({code}) ...", end=" ", flush=True)
        t0 = time.time()
        df, method, status = fetch_industry(code, name)
        elapsed = time.time() - t0
        if df is not None and not df.empty:
            fpath = os.path.join(output_dir, f"{name}.csv")
            df.to_csv(fpath, index=False, encoding="utf-8-sig")
            n_rows = len(df)
            date_min = df["日期"].min().strftime("%Y-%m-%d")
            date_max = df["日期"].max().strftime("%Y-%m-%d")
            n_cols = len(df.columns)
            print(f"✅ {n_rows}行 [{date_min} ~ {date_max}] {n_cols}列 via {method} ({elapsed:.1f}s)")
            results.append({"行业代码": code, "行业名称": name, "状态": "成功",
                            "行数": n_rows, "列数": n_cols,
                            "最早日期": date_min, "最晚日期": date_max,
                            "数据源": method, "耗时_秒": round(elapsed, 1)})
            all_dfs.append(df)
            success_count += 1
        else:
            print(f"❌ 失败 ({status}) ({elapsed:.1f}s)")
            results.append({"行业代码": code, "行业名称": name, "状态": "失败",
                            "行数": 0, "列数": 0, "最早日期": "", "最晚日期": "",
                            "数据源": method, "耗时_秒": round(elapsed, 1), "错误": status})
            fail_count += 1
        time.sleep(1.0)

    print("\n" + "=" * 70)
    print("合并全量表 ...")
    if all_dfs:
        common_cols = set(all_dfs[0].columns)
        for d in all_dfs[1:]:
            common_cols = common_cols & set(d.columns)
        common_cols = sorted(common_cols)
        priority = ["日期", "行业代码", "行业名称", "开盘", "收盘", "最高", "最低",
                     "成交量_亿股", "成交额_亿元", "涨跌幅_pct", "换手率_pct",
                     "市盈率", "市净率", "成交额占比_pct", "流通市值_亿元", "股息率_pct"]
        ordered = [c for c in priority if c in common_cols]
        ordered += [c for c in common_cols if c not in ordered]
        merged = pd.concat([d[ordered] for d in all_dfs], ignore_index=True)
        merged = merged.sort_values(["日期", "行业代码"]).reset_index(drop=True)
        all_path = os.path.join(output_dir, "sw31_daily_all.csv")
        merged.to_csv(all_path, index=False, encoding="utf-8-sig")
        print(f"✅ 全量表: {len(merged)}行 x {len(ordered)}列 → {all_path}")
        link_path = os.path.join(project_root, "raw_data", "sw31_daily_all.csv")
        if not os.path.exists(link_path):
            try:
                os.symlink(all_path, link_path)
            except Exception:
                pass

    summary_df = pd.DataFrame(results)
    summary_path = os.path.join(output_dir, "_fetch_summary.csv")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print(f"  拉取完成: {success_count}/31 成功, {fail_count}/31 失败")
    if all_dfs:
        total_rows = sum(len(d) for d in all_dfs)
        print(f"  总数据量: {total_rows:,} 行")
    print(f"  摘要文件: {summary_path}")
    print("=" * 70)

    print("\n数据覆盖分组:")
    for r in sorted(results, key=lambda x: x.get("最早日期", "9999")):
        if r["状态"] == "成功":
            print(f"  {r['行业名称']:6s} {r['行业代码']} | "
                  f"{r['最早日期']} ~ {r['最晚日期']} | "
                  f"{r['行数']:>5d}行 | {r['数据源']}")
        else:
            print(f"  {r['行业名称']:6s} {r['行业代码']} | ❌ {r.get('错误', 'unknown')}")

    if fail_count > 0:
        print(f"\n⚠️  {fail_count}个行业拉取失败，请检查网络或akshare版本后重试。")
    else:
        print("\n✅ 全部31个行业数据拉取成功！")

    return success_count, fail_count


if __name__ == "__main__":
    main()
