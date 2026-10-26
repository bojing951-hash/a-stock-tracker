#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
申万行业指数日线拉取模块 (阶段1/数据接入层)
================================================
功能：
  - 读取 raw_data/sw_index_mapping.json 获取22行业映射
  - 对每个行业，输出 2015-01-05 至今的日线数据到 raw_data/index_daily/{行业名}.csv
  - 输出列: date,open,close,high,low,volume,amount

数据策略（双源，优先稳定）：
  1) 主源：raw_data/sw_industry_daily.csv —— 申万二级行业日线全集（eastmoney BK板块），
     2015-01-05 ~ 2026-06-18，覆盖全部22行业（养殖业用父行业"农林牧渔"）。
     该源稳定、完整，作为默认与回退源。
  2) 增量源：akshare index_zh_a_hist(symbol=申万代码) / stock_zh_index_daily_em ——
     用于把数据更新到"今天"。当前网络环境下 eastmoney push2 接口间歇性被重置，
     故增量采用"尽力而为"：失败则降级到主源最新日期并打印提示，不中断流程。

用法：
  python3 data_feeds/fetch_sw_index.py             # 拉取全部22个行业
  python3 data_feeds/fetch_sw_index.py --test      # 只拉3个一级行业(基础化工/煤炭/国防军工)
  python3 data_feeds/fetch_sw_index.py --incremental  # 尝试用akshare增量追加最新数据
"""
import os
import sys
import time
import json
import argparse

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw_data")
OUT_DIR = os.path.join(RAW_DIR, "index_daily")
MAPPING_PATH = os.path.join(RAW_DIR, "sw_index_mapping.json")
LOCAL_DAILY = os.path.join(RAW_DIR, "sw_industry_daily.csv")

START_DATE = "20150101"
END_DATE = "20260621"

# 测试用：3个一级行业
TEST_INDUSTRIES = ["基础化工", "煤炭", "国防军工"]

# 部分二级行业需用父行业名（本地数据集里没有"养殖业"，用"农林牧渔"）
LOCAL_NAME_RESOLVE = {
    "养殖业": "农林牧渔",
}


# ---------- 本地主源提取 ----------
def _load_local_daily():
    """加载本地申万行业日线全集，返回 {行业名: DataFrame} 字典"""
    import pandas as pd
    if not os.path.exists(LOCAL_DAILY):
        return None
    df = pd.read_csv(LOCAL_DAILY, dtype={"industry_code": str})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    out = {}
    for name, g in df.groupby("industry_name"):
        g = g.sort_values("date")
        out[str(name)] = g
    return out


def fetch_from_local(industry, local_map):
    """从本地主源提取单行业日线，返回标准 DataFrame[date,open,close,high,low,volume,amount]"""
    import pandas as pd
    src = LOCAL_NAME_RESOLVE.get(industry, industry)
    g = local_map.get(src)
    if g is None or len(g) == 0:
        return None
    out = g[["date", "open", "close", "high", "low", "volume", "amount"]].copy()
    # 过滤起始日期之后
    out = out[out["date"] >= "2015-01-01"].reset_index(drop=True)
    return out


# ---------- akshare 增量源 ----------
def _clean_env_proxy():
    """清除代理环境变量（本环境代理7890返回502，直连可用）"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def fetch_from_akshare(industry, mapping_entry):
    """
    用 akshare 拉取申万一级行业指数日线。
    申万一级代码(801xxx) 走 index_zh_a_hist。返回标准 DataFrame 或 None。
    仅对 type==L1 尝试；L2/concept 无对应稳定接口时返回 None（交由主源）。
    """
    try:
        import akshare as ak
    except Exception as e:
        print(f"    [akshare] 导入失败: {e}")
        return None

    _clean_env_proxy()
    t = mapping_entry.get("type")
    # 取候选代码：L1 用 sw_code；其余尝试父级一级代码
    code = mapping_entry.get("sw_code") or mapping_entry.get("sw_parent_code")
    if not code:
        return None
    code_num = code.split(".")[0]  # "801030"

    # 尝试 index_zh_a_hist（申万一级主接口）
    for attempt in range(3):
        try:
            df = ak.index_zh_a_hist(symbol=code_num, period="daily",
                                    start_date=START_DATE, end_date=END_DATE)
            if df is not None and len(df) > 0:
                # 列名对齐: 日期/开盘/收盘/最高/最低/成交量/成交额
                col_map = {}
                for c in df.columns:
                    cl = str(c)
                    if "日期" in cl: col_map[c] = "date"
                    elif "开盘" in cl: col_map[c] = "open"
                    elif "收盘" in cl: col_map[c] = "close"
                    elif "最高" in cl: col_map[c] = "high"
                    elif "最低" in cl: col_map[c] = "low"
                    elif "成交量" in cl: col_map[c] = "volume"
                    elif "成交额" in cl: col_map[c] = "amount"
                df = df.rename(columns=col_map)
                keep = [c for c in ["date", "open", "close", "high", "low", "volume", "amount"]
                        if c in df.columns]
                df = df[keep].copy()
                df["date"] = df["date"].astype(str)
                return df
        except Exception as e:
            time.sleep(1.5)
    return None


# ---------- 单行业拉取 ----------
def fetch_one(industry, mapping_entry, local_map, use_akshare_incremental):
    """返回 (DataFrame, source_str, info_dict)"""
    # 1) 主源：本地
    df_local = fetch_from_local(industry, local_map)
    source = "local(sw_industry_daily)"
    df = df_local

    # 2) 增量：尝试 akshare（仅当要求，且本地数据非今天）
    if use_akshare_incremental:
        df_ak = fetch_from_akshare(industry, mapping_entry)
        if df_ak is not None and len(df_ak) > 0:
            import pandas as pd
            # 以 akshare 为准合并（akshare 通常更新到最新交易日）
            if df_local is not None and len(df_local) > 0:
                local_end = df_local["date"].max()
                extra = df_ak[df_ak["date"] > local_end]
                if len(extra) > 0:
                    df = pd.concat([df_local, extra], ignore_index=True).drop_duplicates("date").sort_values("date")
                    source = f"local+akshare增量(+{len(extra)}行)"
                else:
                    source = "local(akshare无新增)"
            else:
                df = df_ak.sort_values("date").reset_index(drop=True)
                source = "akshare"
        else:
            source = "local(akshare增量失败,已降级)"

    if df is None or len(df) == 0:
        return None, source, {"rows": 0}

    info = {
        "rows": int(len(df)),
        "start": str(df["date"].iloc[0]),
        "end": str(df["date"].iloc[-1]),
        "actual_code": mapping_entry.get("actual_em_code", ""),
        "source": source,
    }
    return df, source, info


# ---------- 主流程 ----------
def main():
    parser = argparse.ArgumentParser(description="申万行业指数日线拉取")
    parser.add_argument("--test", action="store_true", help="只拉取3个一级行业")
    parser.add_argument("--incremental", action="store_true",
                        help="尝试用akshare增量追加最新数据")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    if args.test:
        targets = [i for i in TEST_INDUSTRIES if i in mapping]
    else:
        targets = list(mapping.keys())

    local_map = _load_local_daily()
    if local_map is None:
        print(f"[警告] 本地主源 {LOCAL_DAILY} 不存在，将仅依赖 akshare（可能不稳定）")

    print(f"=== 申万行业指数日线拉取 ===")
    print(f"目标行业数: {len(targets)} | 模式: {'测试(3个L1)' if args.test else '全部'} | "
          f"akshare增量: {'开' if args.incremental else '关'}")
    print("-" * 72)

    results = []
    for ind in targets:
        df, source, info = fetch_one(ind, mapping[ind], local_map, args.incremental)
        if df is None:
            print(f"  ✗ {ind}: 拉取失败")
            results.append((ind, info))
            continue
        out_path = os.path.join(OUT_DIR, f"{ind}.csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        results.append((ind, info))
        print(f"  ✓ {ind:8s} [{mapping[ind]['actual_em_code']:>8s}] {info['rows']:>5d}行  "
              f"{info['start']} ~ {info['end']}  ({source})")

    # 汇总
    print("-" * 72)
    ok = [r for _, r in results if r["rows"] > 0]
    print(f"完成: {len(ok)}/{len(targets)} 个行业成功，输出到 {OUT_DIR}")
    return results


if __name__ == "__main__":
    main()
