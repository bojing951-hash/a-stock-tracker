# -*- coding: utf-8 -*-
"""
增量数据更新 (阶段3)
================================================
1. 读取现有CSV最后日期，只拉该日期之后新数据，追加到CSV末尾
2. 行业指数日线: 从本地 sw_industry_daily.csv 主源增量 + akshare在线增量(尽力而为)
3. 6类核心指标: 时序指标增量追加; 快照(申万估值)全量刷新; 生猪覆盖更新

网络说明: 本环境代理7890返回502,启动即清代理强制直连;
         eastmoney push2接口间歇性被重置, akshare增量失败时降级为"无新增"并记录。
"""
import os
import sys
import time
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "data_feeds"))
INDEX_DIR = os.path.join(BASE_DIR, "raw_data", "index_daily")
IND_DIR = os.path.join(BASE_DIR, "raw_data", "indicators")
LOCAL_DAILY = os.path.join(BASE_DIR, "raw_data", "sw_industry_daily.csv")
TODAY = time.strftime("%Y%m%d")  # 动态日期(2026-09-30修复:原硬编码20260621,增量上限被钉死在6/21)

# 22行业(周期CSV口径, 含有色/通信设备)
INDUSTRIES = sorted(pd.read_csv(os.path.join(
    BASE_DIR, "raw_data", "industry_cycle.csv"))["行业名称"].astype(str).unique())

# 行业名 -> 申万一级/二级行业指数代码(ak.index_hist_sw用, 2026-09-30逐一对账核实)
SW_CODE_MAP = {
    "电子": "801080", "半导体": "801081", "消费电子": "801085",
    "光伏设备": "801735", "电池": "801737", "电力设备": "801730", "风电设备": "801736",
    "能源金属": "801056", "有色金属": "801050", "贵金属": "801053",
    "国防军工": "801740", "汽车零部件": "801093",
    "通信设备": "801102", "计算机设备": "801101", "软件开发": "801104", "传媒": "801760",
    "医疗器械": "801153", "非银金融": "801790", "房地产": "801180",
    "食品饮料": "801120", "基础化工": "801030", "煤炭": "801950",
}


def _clean_proxy():
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def _last_date(path, date_col="date"):
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, usecols=[date_col])
        return str(df[date_col].iloc[-1]).strip()
    except Exception:
        return None


class IncrementalUpdater:
    def __init__(self):
        _clean_proxy()
        self.report = []

    def _log(self, name, status, rows=0, detail=""):
        self.report.append({"目标": name, "状态": status, "新增行": rows, "说明": detail})
        print(f"  [{status:6s}] {name:24s} +{rows:>4d}行  {detail}")

    # ---------- 行业指数增量 ----------
    def update_sw_index(self, industry_name):
        path = os.path.join(INDEX_DIR, f"{industry_name}.csv")
        last = _last_date(path)
        # 1) 本地主源增量(若 sw_industry_daily.csv 比单行业CSV更新)
        added = 0
        if os.path.exists(LOCAL_DAILY):
            full = pd.read_csv(LOCAL_DAILY, dtype={"industry_code": str})
            # 单行业CSV用的源名(养殖业->农林牧渔 在此口径不涉及)
            sub = full[full["industry_name"].astype(str) == industry_name]
            if len(sub):
                sub = sub.sort_values("date")
                if last is None or sub["date"].astype(str).iloc[-1] > last:
                    new = sub[sub["date"].astype(str) > (last or "")][
                        ["date", "open", "close", "high", "low", "volume", "amount"]]
                    if len(new):
                        old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()
                        merged = pd.concat([old, new], ignore_index=True).drop_duplicates("date").sort_values("date")
                        merged.to_csv(path, index=False, encoding="utf-8-sig")
                        added = len(new)
        # 2) 申万指数在线增量(2026-09-30接入,尽力而为,失败不报错)
        # 本地CSV是东财板块口径价格,与申万801系列价格水平不同:
        # 以重叠日收盘价算换算比例,把申万新数据折算到本地口径后拼接,保证序列连续可比
        online_added, online_note = 0, ""
        try:
            import akshare as ak
            code = SW_CODE_MAP.get(industry_name)
            if not code:
                online_note = "无申万代码映射"
            else:
                time.sleep(0.4)  # 22个行业连续请求,稍作间隔避免被限流
                sw = ak.index_hist_sw(symbol=code, period="day")
                sw = sw.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                        "最高": "high", "最低": "low",
                                        "成交量": "volume", "成交额": "amount"})
                sw["date"] = sw["date"].astype(str).str[:10]
                sw = sw[["date", "open", "close", "high", "low", "volume", "amount"]].sort_values("date")
                last = _last_date(path)  # 重读:本地源合并后last可能已前移
                if last is None:
                    online_note = "本地无历史,跳过在线拼接"
                else:
                    base = sw[sw["date"] <= last]
                    old = pd.read_csv(path)
                    if base.empty:
                        online_note = f"申万无{last}及之前数据"
                    else:
                        # 换算比例: 每列各自按重叠日"本地值/申万值"折算
                        # (价格口径不同,成交量/成交额单位也不同——本地额为元,申万为亿元,逐列换算保证连续)
                        new = sw[sw["date"] > last].copy()
                        if len(new):
                            scales = {}
                            for c in ("open", "close", "high", "low", "volume", "amount"):
                                sv = float(base[c].iloc[-1])
                                scales[c] = (float(old[c].iloc[-1]) / sv) if sv else 1.0
                                new[c] = (new[c].astype(float) * scales[c]).round(2)
                            merged = pd.concat([old, new], ignore_index=True).drop_duplicates("date").sort_values("date")
                            merged.to_csv(path, index=False, encoding="utf-8-sig")
                            online_added = len(new)
                            online_note = f"申万{code}已拼到{new['date'].iloc[-1]},价格比例{scales['close']:.4f}"
                        else:
                            online_note = f"申万{code}亦无新增"
        except Exception as e:
            online_note = f"申万在线失败: {repr(e)[:60]}"
        self._log(f"指数:{industry_name}", "OK", added + online_added,
                  f"本地+{added} 在线+{online_added} {online_note}")

    # ---------- 指标增量 ----------
    def _ak(self, fn_label, fn):
        try:
            return fn()
        except Exception as e:
            self._log(fn_label, "SKIP", 0, f"akshare失败降级: {repr(e)[:80]}")
            return None

    def update_indicators(self):
        import akshare as ak
        _clean_proxy()
        # 碳酸锂期货(时序, 增量)
        self._update_ts("lithium_carbonate_futures", "lithium",
                        lambda: ak.futures_main_sina(symbol="LC0", start_date="20230701", end_date=TODAY),
                        rename={"日期": "date", "开盘价": "open", "最高价": "high", "最低价": "low",
                                "收盘价": "close", "成交量": "volume", "持仓量": "open_interest",
                                "动态结算价": "settle"})
        # 上海金(时序, 增量)
        self._update_ts("gold_price_sge", "gold_sge",
                        lambda: ak.spot_golden_benchmark_sge(),
                        rename={"交易时间": "date", "晚盘价": "price_pm", "早盘价": "price_am"},
                        derive_price=True)
        # 螺纹钢(时序, 增量)
        self._update_ts("rebar_spot", "rebar",
                        lambda: ak.spot_price_qh(symbol="螺纹钢"),
                        rename={"日期": "date", "期货收盘价": "futures_close", "现货价格": "spot"})
        # 两融余额(时序, 增量 - 上交所近段)
        self._update_margin(ak)
        # 生猪(覆盖更新: 接口只返回近期)
        self._update_hog(ak)
        # 申万估值(快照, 全量刷新)
        self._update_valuation(ak)

    def _update_ts(self, name, label, fetch_fn, rename=None, derive_price=False):
        path = os.path.join(IND_DIR, f"{name}.csv")
        last = _last_date(path)
        df = self._ak(name, fetch_fn)
        if df is None:
            return
        df = df.rename(columns=rename or {})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        if derive_price and "price_pm" in df.columns:
            df["price"] = df["price_pm"].fillna(df.get("price_am"))
        df = df.sort_values("date") if "date" in df.columns else df
        if last and "date" in df.columns:
            new = df[df["date"] > last]
        else:
            new = df
        if os.path.exists(path) and len(new):
            old = pd.read_csv(path)
            # 对齐列
            cols = [c for c in old.columns if c in new.columns] or new.columns
            merged = pd.concat([old[cols], new[cols]], ignore_index=True).drop_duplicates("date").sort_values("date")
            merged.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(name, "OK", len(new), f"last={last} -> {merged['date'].iloc[-1]}")
        elif len(new) == 0:
            self._log(name, "OK", 0, f"已是最新(last={last})")
        else:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(name, "OK", len(df), "首次写入")

    def _update_margin(self, ak):
        path = os.path.join(IND_DIR, "margin_balance.csv")
        last = _last_date(path)
        last_num = (last or "20260101").replace("-", "")[:8]
        today = TODAY
        try:
            d = ak.stock_margin_sse(start_date=last_num, end_date=today)
        except Exception as e:
            self._log("margin_balance", "SKIP", 0, f"两融接口失败: {repr(e)[:60]}")
            return
        if d is None or len(d) == 0:
            self._log("margin_balance", "OK", 0, "无新增")
            return
        d = d.rename(columns={"信用交易日期": "date", "融资余额": "margin_financing",
                              "融券余量金额": "margin_securities_value", "融资融券余额": "total_balance"})
        d["date"] = pd.to_datetime(d["date"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
        d["total_balance_yi"] = (d["total_balance"].astype(float) / 1e8).round(2)
        if last:
            new = d[d["date"] > last]
        else:
            new = d
        if os.path.exists(path) and len(new):
            old = pd.read_csv(path)
            cols = [c for c in old.columns if c in new.columns] or new.columns
            merged = pd.concat([old[cols], new[cols]], ignore_index=True).drop_duplicates("date").sort_values("date")
            merged.to_csv(path, index=False, encoding="utf-8-sig")
            self._log("margin_balance", "OK", len(new), f"last={last}")
        else:
            self._log("margin_balance", "OK", max(0, len(new)), "已是最新或无新增")

    def _update_hog(self, ak):
        path = os.path.join(IND_DIR, "hog_price.csv")
        try:
            trend = ak.spot_hog_year_trend_soozhu().rename(
                columns={"日期": "date", "价格": "price"})
            trend["date"] = pd.to_datetime(trend["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            trend = trend.sort_values("date").reset_index(drop=True)
            trend["latest_provinces"] = ""
            trend.to_csv(path, index=False, encoding="utf-8-sig")
            self._log("hog_price", "OK", len(trend), f"覆盖更新 末={trend['date'].iloc[-1]}")
        except Exception as e:
            self._log("hog_price", "SKIP", 0, f"生猪接口失败: {repr(e)[:60]}")

    def _update_valuation(self, ak):
        path = os.path.join(IND_DIR, "sw_valuation.csv")
        from datetime import datetime
        try:
            df = ak.sw_index_first_info().rename(columns={
                "行业代码": "sw_code", "行业名称": "industry", "成份个数": "constituents",
                "静态市盈率": "pe_static", "TTM(滚动)市盈率": "pe_ttm",
                "市净率": "pb", "静态股息率": "dividend_yield"})
            df["snapshot_date"] = datetime.now().strftime("%Y-%m-%d")
            df.to_csv(path, index=False, encoding="utf-8-sig")
            self._log("sw_valuation", "OK", len(df), f"全量刷新快照({len(df)}行业)")
        except Exception as e:
            self._log("sw_valuation", "SKIP", 0, f"估值接口失败: {repr(e)[:60]}")

    def update_all(self):
        print("=== 增量更新: 22行业指数 ===")
        for ind in INDUSTRIES:
            self.update_sw_index(ind)
        print("\n=== 增量更新: 6类核心指标 ===")
        self.update_indicators()
        return pd.DataFrame(self.report)


if __name__ == "__main__":
    upd = IncrementalUpdater()
    rep = upd.update_all()
    print("\n=== 增量更新汇总 ===")
    print(rep.to_string(index=False))
    print(f"\n目标数: {len(rep)} | 成功: {(rep['状态']=='OK').sum()} | 跳过: {(rep['状态']=='SKIP').sum()}")
    print(f"新增行总计: {rep['新增行'].sum()}")
