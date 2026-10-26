#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产能周期核心指标拉取模块 (阶段1/数据接入层)
================================================
接入6类产能周期核心指标（akshare 免费接口），统一保存到 raw_data/indicators/。

指标清单：
  4a 碳酸锂期货价格 LC0     -> lithium_carbonate_futures.csv   (能源金属/电池)
  4b 上海金基准价 SGE       -> gold_price_sge.csv              (贵金属)
  4c 两融余额(上交所汇总)   -> margin_balance.csv              (非银金融)
  4d 螺纹钢现货价           -> rebar_spot.csv                  (钢铁/基础化工)
  4e 生猪价格(年内走势)     -> hog_price.csv                   (养殖业)
  4f 申万行业 PE/PB 估值     -> sw_valuation.csv                (全行业参考)

设计要点：
  - 本环境代理 7890 返回 502，故启动即清除代理环境变量，强制直连。
  - 每个指标独立 try/except，单点失败不中断整体流程，打印错误信息。
  - 统一打印：指标名、数据行数、起止日期、最新值。

用法：
  python3 data_feeds/fetch_indicators.py
  python3 data_feeds/fetch_indicators.py --incremental   # 预留增量（当前等同全量）
"""
import os
import sys
import argparse
from datetime import datetime

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw_data")
OUT_DIR = os.path.join(RAW_DIR, "indicators")


def _clean_proxy():
    """清除代理环境变量（代理7890返回502，直连可用）"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def _save_csv(df, name):
    path = os.path.join(OUT_DIR, f"{name}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _fmt_date_col(df, col):
    """把日期列标准化为 YYYY-MM-DD 字符串"""
    import pandas as pd
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


# ---------- 各指标 ----------
def fetch_lithium_carbonate():
    """4a 碳酸锂期货主力 LC0（2023-07上市）"""
    import akshare as ak
    df = ak.futures_main_sina(symbol="LC0", start_date="20230701", end_date="20260621")
    df = df.rename(columns={
        "日期": "date", "开盘价": "open", "最高价": "high", "最低价": "low",
        "收盘价": "close", "成交量": "volume", "持仓量": "open_interest",
        "动态结算价": "settle",
    })
    df = _fmt_date_col(df, "date")
    df = df.sort_values("date").reset_index(drop=True)
    latest = float(df.iloc[-1]["close"])
    info = {"rows": len(df), "start": df["date"].iloc[0], "end": df["date"].iloc[-1],
            "latest": f"{latest/1e4:.2f}万元/吨({int(latest)}元/吨)"}
    return df, "lithium_carbonate_futures", info


def fetch_gold_sge():
    """4b 上海金基准价（SGE）"""
    import akshare as ak
    df = ak.spot_golden_benchmark_sge()
    df = df.rename(columns={"交易时间": "date", "晚盘价": "price_pm", "早盘价": "price_am"})
    df = _fmt_date_col(df, "date")
    # 取晚盘价为主价格（缺失则用早盘）
    df["price"] = df["price_pm"].fillna(df["price_am"])
    df = df.sort_values("date").reset_index(drop=True)
    latest = df.iloc[-1]["price"]
    info = {"rows": len(df), "start": df["date"].iloc[0], "end": df["date"].iloc[-1],
            "latest": f"{latest:.2f}元/克"}
    return df, "gold_price_sge", info


def fetch_margin_balance():
    """4c 两融余额（上交所汇总，融资融券余额=总余额）"""
    import akshare as ak
    # 上交所两融余额逐日汇总（akshare一次仅返回约20日，分批拉取覆盖2023至今）
    import pandas as pd
    frames = []
    # 按季度分批拉，避免单次返回上限
    quarters = []
    y, m = 2023, 1
    while (y, m) <= (2026, 6):
        s = f"{y}{m:02d}01"
        # 季末月
        em = m + 2
        ey = y
        if em > 12:
            em -= 12; ey += 1
        import calendar
        last = calendar.monthrange(ey, em)[1]
        e = f"{ey}{em:02d}{last:02d}"
        quarters.append((s, e))
        m += 3
        if m > 12:
            m -= 12; y += 1
    for s, e in quarters:
        try:
            d = ak.stock_margin_sse(start_date=s, end_date=e)
            if d is not None and len(d) > 0:
                frames.append(d)
        except Exception:
            pass
    if not frames:
        raise RuntimeError("上交所两融接口全部批次失败")
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={
        "信用交易日期": "date", "融资余额": "margin_financing",
        "融券余量金额": "margin_securities_value", "融资融券余额": "total_balance",
    })
    df = _fmt_date_col(df, "date")
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    # 转为亿元
    df["total_balance_yi"] = (df["total_balance"].astype(float) / 1e8).round(2)
    latest = df.iloc[-1]["total_balance_yi"]
    info = {"rows": len(df), "start": df["date"].iloc[0], "end": df["date"].iloc[-1],
            "latest": f"{latest:.0f}亿元"}
    return df, "margin_balance", info


def fetch_rebar_spot():
    """4d 螺纹钢现货价（含期货收盘价）"""
    import akshare as ak
    df = ak.spot_price_qh(symbol="螺纹钢")
    df = df.rename(columns={"日期": "date", "期货收盘价": "futures_close", "现货价格": "spot"})
    df = _fmt_date_col(df, "date")
    df = df.sort_values("date").reset_index(drop=True)
    latest = df.iloc[-1]["spot"]
    info = {"rows": len(df), "start": df["date"].iloc[0], "end": df["date"].iloc[-1],
            "latest": f"{latest:.0f}元/吨(现货)"}
    return df, "rebar_spot", info


def fetch_hog_price():
    """4e 生猪价格（年内走势 + 最新各省均价）"""
    import akshare as ak
    import pandas as pd
    # 年内走势（日频全国）
    trend = ak.spot_hog_year_trend_soozhu()
    trend = trend.rename(columns={"日期": "date", "价格": "price"})
    trend = _fmt_date_col(trend, "date")
    trend = trend.sort_values("date").reset_index(drop=True)
    # 最新各省
    try:
        prov = ak.spot_hog_soozhu()
        prov = prov.rename(columns={"省份": "province", "价格": "price", "涨跌幅": "chg"})
        latest_national = float(trend.iloc[-1]["price"])
    except Exception:
        prov = pd.DataFrame()
        latest_national = float(trend.iloc[-1]["price"])
    # 合并：走势为主表，省份数据单独存一列备注（存宽表不便，分两段保存）
    out = trend.copy()
    if len(prov):
        out["latest_provinces"] = ""
        prov_summary = "; ".join(f"{r['province']}{r['price']}" for _, r in prov.iterrows())
        out.loc[out.index[-1], "latest_provinces"] = prov_summary
    info = {"rows": len(out), "start": out["date"].iloc[0], "end": out["date"].iloc[-1],
            "latest": f"{latest_national:.2f}元/公斤(全国)"}
    return out, "hog_price", info


def fetch_sw_valuation():
    """4f 申万一级行业 PE/PB/股息率估值（31个一级行业，快照）"""
    import akshare as ak
    df = ak.sw_index_first_info()
    df = df.rename(columns={
        "行业代码": "sw_code", "行业名称": "industry", "成份个数": "constituents",
        "静态市盈率": "pe_static", "TTM(滚动)市盈率": "pe_ttm",
        "市净率": "pb", "静态股息率": "dividend_yield",
    })
    today = datetime.now().strftime("%Y-%m-%d")
    df["snapshot_date"] = today
    info = {"rows": len(df), "start": today, "end": today,
            "latest": f"{len(df)}个一级行业 PE_TTM/PB 快照"}
    return df, "sw_valuation", info


# ---------- 主流程 ----------
INDICATORS = [
    ("碳酸锂期货", fetch_lithium_carbonate),
    ("上海金基准价", fetch_gold_sge),
    ("两融余额", fetch_margin_balance),
    ("螺纹钢现货", fetch_rebar_spot),
    ("生猪价格", fetch_hog_price),
    ("申万估值", fetch_sw_valuation),
]


def main():
    parser = argparse.ArgumentParser(description="产能周期核心指标拉取")
    parser.add_argument("--incremental", action="store_true", help="增量更新（当前等同全量）")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    _clean_proxy()

    print("=== 产能周期核心指标拉取 ===")
    print(f"输出目录: {OUT_DIR}")
    print("-" * 72)

    results = {}
    for label, fn in INDICATORS:
        try:
            df, name, info = fn()
            path = _save_csv(df, name)
            results[label] = {"status": "OK", "info": info, "path": path}
            print(f"  ✓ {label:10s} {info['rows']:>5d}行  {info.get('start',''):>10s} ~ "
                  f"{info.get('end',''):>10s}  最新: {info['latest']}")
        except Exception as e:
            results[label] = {"status": f"ERR: {repr(e)[:140]}"}
            print(f"  ✗ {label:10s} 失败: {repr(e)[:140]}")

    print("-" * 72)
    ok = sum(1 for r in results.values() if r["status"] == "OK")
    print(f"完成: {ok}/{len(INDICATORS)} 个指标成功")
    return results


if __name__ == "__main__":
    main()
