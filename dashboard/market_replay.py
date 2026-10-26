# -*- coding: utf-8 -*-
"""
市场复盘器 (market_replay.py)
================================================
给定任意时间窗口，自动生成结构化复盘报告：
  1. 大盘分阶段走势(zigzag转折点识别)
  2. 22行业同期涨跌幅排名 + 各子阶段排名变化
  3. 板块轮动链条
  4. 热点主线识别
  5. 临近板块联动分析
  6. 催化剂事件关联
  7. 叠加产能周期阶段标注
"""
import os
import sys
import calendar
import numpy as np
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "dashboard"))

INDEX_DIR = os.path.join(BASE_DIR, "raw_data", "index_daily")
CYCLE_CSV = os.path.join(BASE_DIR, "raw_data", "industry_cycle.csv")
CATALYST_CSV = os.path.join(BASE_DIR, "raw_data", "catalyst_events.csv")
MAPPING = os.path.join(BASE_DIR, "raw_data", "sw_index_mapping.json")
BACKTEST_SUMMARY = os.path.join(BASE_DIR, "backtest", "backtest_results", "cycle_timing_summary.csv")
REPORT_DIR = os.path.join(BASE_DIR, "dashboard", "replay_reports")
CHART_DIR = os.path.join(BASE_DIR, "dashboard", "replay_charts")

# 22行业(周期CSV口径)
INDUSTRIES_22 = sorted(pd.read_csv(CYCLE_CSV)["行业名称"].astype(str).unique())
# 不参与行业排名的大盘指数
BENCHMARK_NAMES = ["上证指数", "沪深300", "创业板指", "中证500", "深证成指", "上证50", "科创50"]

# 产业链关联
INDUSTRY_CHAINS = {
    "新能源链": ["能源金属", "电池", "光伏设备", "风电设备", "电力设备"],
    "TMT链": ["计算机设备", "软件开发", "通信设备", "传媒", "电子", "半导体"],
    "消费电子链": ["半导体", "电子", "消费电子"],
    "金融地产链": ["非银金融", "房地产"],
    "上游周期链": ["煤炭", "基础化工", "有色金属", "能源金属"],
    "军工链": ["国防军工"],
    "贵金属": ["贵金属"],
    "消费链": ["食品饮料"],
}


def _norm_date(v):
    v = str(v).strip()
    if "至今" in v or v in ("nan", ""):
        return "2026-06-22"
    if len(v) == 7:
        return f"{v}-01"
    return v


def parse_time_window(window_str):
    """解析时间窗口快捷方式 -> (start, end) YYYY-MM-DD"""
    w = window_str.strip()
    today = pd.Timestamp("2026-06-22")
    # recentN
    if w.startswith("recent"):
        n = int(w.replace("recent", ""))
        # 用上证指数交易日算
        sh = os.path.join(INDEX_DIR, "上证指数.csv")
        if os.path.exists(sh):
            d = pd.read_csv(sh, usecols=[0])
            end = str(d.iloc[-1, 0])
            start = str(d.iloc[max(0, len(d) - n), 0])
            return start, end
        return (today - pd.Timedelta(days=n)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    if w.lower() == "ytd":
        return f"{today.year}-01-01", today.strftime("%Y-%m-%d")
    # 2025Q1/Q2/Q3/Q4
    import re
    m = re.match(r"^(\d{4})Q([1-4])$", w)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        sm = {1: 1, 2: 4, 3: 7, 4: 10}[q]
        em = sm + 2
        last = calendar.monthrange(y, em)[1]
        return f"{y}-{sm:02d}-01", f"{y}-{em:02d}-{last:02d}"
    # 2025H1/H2
    m = re.match(r"^(\d{4})H([12])$", w)
    if m:
        y, h = int(m.group(1)), int(m.group(2))
        if h == 1:
            return f"{y}-01-01", f"{y}-06-30"
        return f"{y}-07-01", f"{y}-12-31"
    # 2025 (全年)
    if re.match(r"^\d{4}$", w):
        return f"{w}-01-01", f"{w}-12-31"
    # 202502 (单月)
    m = re.match(r"^(\d{4})(\d{2})$", w)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        last = calendar.monthrange(y, mo)[1]
        return f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{last:02d}"
    # 20250205-20250307
    m = re.match(r"^(\d{4})(\d{2})(\d{2})-(\d{4})(\d{2})(\d{2})$", w)
    if m:
        g = m.groups()
        return f"{g[0]}-{g[1]}-{g[2]}", f"{g[3]}-{g[4]}-{g[5]}"
    # 已是标准日期
    if re.match(r"^\d{4}-\d{2}-\d{2}$", w):
        return w, w
    raise ValueError(f"无法解析时间窗口: {w}")


class MarketReplay:
    def __init__(self, base_dir, start_date, end_date, label=None):
        self.base_dir = base_dir
        self.start = pd.to_datetime(start_date)
        self.end = pd.to_datetime(end_date)
        self.label = label or f"{start_date}~{end_date}"
        self.index_data = {}
        self.benchmark = None
        self.cycles = None
        self.catalysts = None
        self.mapping = None
        self.backtest_summary = None
        self.phases = None
        self.rankings = None

    # ---------- 数据加载 ----------
    def load_data(self):
        # 1. 22行业日线
        for ind in INDUSTRIES_22:
            p = os.path.join(INDEX_DIR, f"{ind}.csv")
            if not os.path.exists(p):
                continue
            df = pd.read_csv(p)
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= self.start) & (df["date"] <= self.end)].sort_values("date").reset_index(drop=True)
            if len(df) >= 2:
                self.index_data[ind] = df
        # 2. 大盘基准
        bp = os.path.join(INDEX_DIR, "上证指数.csv")
        if os.path.exists(bp):
            df = pd.read_csv(bp)
            df["date"] = pd.to_datetime(df["date"])
            self.benchmark = df[(df["date"] >= self.start) & (df["date"] <= self.end)].sort_values("date").reset_index(drop=True)
        # 3. 催化剂
        if os.path.exists(CATALYST_CSV):
            cat = pd.read_csv(CATALYST_CSV)
            cat["date"] = pd.to_datetime(cat["date"])
            self.catalysts = cat[(cat["date"] >= self.start) & (cat["date"] <= self.end)].sort_values("date").reset_index(drop=True)
        else:
            self.catalysts = pd.DataFrame()
        # 4. 产能周期
        self.cycles = pd.read_csv(CYCLE_CSV)
        # 5. 回测绩效
        if os.path.exists(BACKTEST_SUMMARY):
            self.backtest_summary = pd.read_csv(BACKTEST_SUMMARY).set_index("行业名称")
        return self

    # ---------- 1. 大盘阶段识别 (zigzag + 成交量确认) ----------
    def detect_market_phases(self, min_move_pct=2.5, min_days=5, use_volume=True):
        """
        自适应阶段识别: zigzag转折点 + 成交量确认。
        thr=2.5% 对2025Q1切出3阶段(下跌→上涨→下跌)。
        """
        if self.benchmark is None or len(self.benchmark) < 5:
            self.phases = []
            return []
        bm = self.benchmark.reset_index(drop=True)
        prices = bm["close"].astype(float).values
        dates = bm["date"].values
        amounts = bm["amount"].astype(float).values if ("amount" in bm.columns and use_volume) else None
        n = len(prices)

        # zigzag 转折点检测
        pivots = [(0, prices[0])]
        current_dir = None
        last_i, last_p = 0, prices[0]
        for i in range(1, n):
            if current_dir is None:
                chg = (prices[i] - last_p) / last_p * 100
                if chg >= min_move_pct:
                    current_dir = "up"
                elif chg <= -min_move_pct:
                    current_dir = "down"
            elif current_dir == "up":
                hi = last_i + int(np.argmax(prices[last_i:i + 1]))
                hp = prices[hi]
                dd = (prices[i] - hp) / hp * 100
                if dd <= -min_move_pct and (i - last_i) >= min_days:
                    pivots.append((hi, hp))
                    last_i, last_p, current_dir = hi, hp, "down"
            elif current_dir == "down":
                lo = last_i + int(np.argmin(prices[last_i:i + 1]))
                lp = prices[lo]
                bn = (prices[i] - lp) / lp * 100
                if bn >= min_move_pct and (i - last_i) >= min_days:
                    pivots.append((lo, lp))
                    last_i, last_p, current_dir = lo, lp, "up"
        if pivots[-1][0] != n - 1:
            pivots.append((n - 1, prices[-1]))

        # 构建阶段
        raw_phases = []
        for k in range(len(pivots) - 1):
            s, e = pivots[k][0], pivots[k + 1][0]
            if e - s < min_days:
                continue
            ret = (prices[e] / prices[s] - 1) * 100
            t = "上涨" if ret >= min_move_pct * 0.4 else ("下跌" if ret <= -min_move_pct * 0.4 else "震荡")
            raw_phases.append(self._make_phase(k + 1, s, e, ret, t, dates, prices, amounts))

        # 合并相邻同向(转折幅度<thr/2)与过短段
        phases = self._merge_phases(raw_phases, min_move_pct)
        if not phases:
            ret = (prices[-1] / prices[0] - 1) * 100
            phases = [self._make_phase(1, 0, n - 1, ret,
                      "上涨" if ret > 0 else ("下跌" if ret < 0 else "震荡"), dates, prices, amounts)]
        for i, ph in enumerate(phases):
            ph["idx"] = i + 1
        self.phases = phases
        return phases

    def _make_phase(self, idx, s, e, ret, t, dates, prices, amounts):
        """构造阶段字典, 含成交量特征"""
        ph = {"idx": idx, "start": pd.Timestamp(dates[s]), "end": pd.Timestamp(dates[e]),
              "type": t, "return": ret, "days": int(e - s + 1),
              "start_close": float(prices[s]), "end_close": float(prices[e])}
        if amounts is not None:
            seg_amt = amounts[s:e + 1]
            avg_amt = float(np.mean(seg_amt)) if len(seg_amt) else 0
            ph["avg_amount"] = avg_amt
            # 段内成交额趋势(末5日均/首5日均)
            if len(seg_amt) >= 10:
                ratio = np.mean(seg_amt[-5:]) / max(np.mean(seg_amt[:5]), 1e-9)
                ph["amt_trend"] = "放量" if ratio > 1.15 else ("缩量" if ratio < 0.85 else "平稳")
                ph["amt_ratio"] = float(ratio)
            else:
                ph["amt_trend"] = "平稳"; ph["amt_ratio"] = 1.0
            # 成交量标签
            ph["vol_label"] = self._vol_label(t, ph["amt_trend"])
        else:
            ph["vol_label"] = t
        # 匹配催化剂(重要>=4)
        ph["catalyst"] = self._phase_catalyst(ph["start"], ph["end"])
        return ph

    @staticmethod
    def _vol_label(direction, amt_trend):
        return {"上涨": {"放量": "放量上涨", "缩量": "缩量上涨", "平稳": "温和上涨"},
                "下跌": {"放量": "放量下跌", "缩量": "缩量下跌", "平稳": "温和下跌"},
                "震荡": {"放量": "放量震荡", "缩量": "缩量震荡", "平稳": "横盘观望"}
                }.get(direction, {}).get(amt_trend, direction)

    def _phase_catalyst(self, start, end):
        if self.catalysts is None or len(self.catalysts) == 0:
            return []
        sub = self.catalysts[(self.catalysts["date"] >= pd.Timestamp(start)) &
                             (self.catalysts["date"] <= pd.Timestamp(end))]
        return [{"date": str(r["date"].date()), "event": r["event_name"],
                 "direction": r["direction"], "importance": int(r["importance"])}
                for _, r in sub.iterrows() if int(r["importance"]) >= 4]

    @staticmethod
    def _merge_phases(phases, min_move_pct):
        """合并相邻同方向 + 过短段并入前段"""
        if not phases:
            return phases
        merged = [dict(phases[0])]
        for ph in phases[1:]:
            prev = merged[-1]
            same_dir = ph["type"] == prev["type"]
            small_turn = abs(ph["return"]) < min_move_pct * 0.5
            if same_dir or (ph["type"] == "震荡") or small_turn:
                prev["end"] = ph["end"]; prev["days"] += ph["days"]
                prev["return"] = (ph["end_close"] / prev["start_close"] - 1) * 100
                prev["end_close"] = ph["end_close"]
                prev["vol_label"] = prev.get("vol_label", prev["type"])
            else:
                merged.append(dict(ph))
        return merged

    # ---------- 2. 行业排名 ----------
    def _ret_in_range(self, df, s, e):
        sub = df[(df["date"] >= s) & (df["date"] <= e)]
        if len(sub) < 2:
            return np.nan
        return (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100

    def calc_industry_rankings(self, phases=None):
        if phases is None:
            phases = self.phases or []
        rows = []
        for ind, df in self.index_data.items():
            row = {"行业": ind}
            # 全期
            full_ret = self._ret_in_range(df, self.start, self.end)
            row["全期涨跌幅"] = full_ret
            # 各阶段
            for ph in phases:
                r = self._ret_in_range(df, ph["start"], ph["end"])
                row[f"阶段{ph['idx']}"] = r
            rows.append(row)
        rdf = pd.DataFrame(rows)
        # 排名(全期降序)
        rdf = rdf.sort_values("全期涨跌幅", ascending=False).reset_index(drop=True)
        rdf["全期排名"] = rdf.index + 1
        for ph in phases:
            col = f"阶段{ph['idx']}"
            rdf[col + "_排名"] = rdf[col].rank(ascending=False).astype('Int64')
        # 排名变化(末阶段-首阶段)
        if phases and len(phases) >= 2:
            first = f"阶段{phases[0]['idx']}_排名"
            last = f"阶段{phases[-1]['idx']}_排名"
            rdf["排名变化"] = (rdf[first].astype('float') - rdf[last].astype('float'))
        self.rankings = rdf
        return rdf

    # ---------- 2. 成交额热度 ----------
    def calc_sector_heat(self, rolling_window=5):
        """
        行业热度时序: 近N日均成交额 / 22行业总成交额 (成交额占比)。
        回退: 无amount用 volume/自身60日均; 都无则用|涨跌幅|。
        返回 DataFrame index=日期 columns=22行业 values=热度。
        """
        frames = {}
        for ind, df in self.index_data.items():
            d = df[["date", "amount", "volume", "close"]].copy() if "amount" in df.columns \
                else df[["date", "volume", "close"]].copy()
            d = d.sort_values("date").set_index("date")
            if "amount" in d.columns:
                d["heat_raw"] = d["amount"].astype(float).rolling(rolling_window).mean()
            elif "volume" in d.columns:
                v = d["volume"].astype(float)
                ma60 = v.rolling(60, min_periods=5).mean()
                d["heat_raw"] = (v.rolling(rolling_window).mean() / ma60).fillna(1.0)
            else:
                d["heat_raw"] = d["close"].astype(float).pct_change().abs().rolling(rolling_window).mean() * 100
            frames[ind] = d["heat_raw"]
        heat = pd.DataFrame(frames)
        # 若基于成交额占比: 归一化为行和=1
        if "amount" in next(iter(self.index_data.values())).columns:
            row_sum = heat.sum(axis=1).replace(0, np.nan)
            heat = heat.div(row_sum, axis=0)
        self._sector_heat = heat
        return heat

    def detect_heat_cycle(self, industry_name, heat_threshold=None):
        """发酵→顶峰→退潮 周期检测"""
        if not hasattr(self, "_sector_heat") or self._sector_heat is None:
            self.calc_sector_heat()
        heat = self._sector_heat.get(industry_name)
        if heat is None or heat.dropna().empty:
            return None
        heat = heat.dropna()
        has_amount = "amount" in next(iter(self.index_data.values())).columns
        mean_h = heat.mean()
        peak_val = heat.max()
        peak_date = heat.idxmax()
        # 发酵起点: 首次超过均值
        above = heat[heat >= mean_h]
        ferment_start = above.index[0] if len(above) else heat.index[0]
        # 退潮: 顶峰后首次回落到均值以下
        after_peak = heat[heat.index > peak_date]
        below = after_peak[after_peak < mean_h]
        ebb_end = below.index[0] if len(below) else heat.index[-1]
        # 涨跌幅
        df = self.index_data[industry_name]
        def _ret(s, e):
            sub = df[(df["date"] >= s) & (df["date"] <= e)]
            return (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100 if len(sub) >= 2 else 0
        ferment_ret = _ret(ferment_start, peak_date)
        ebb_ret = _ret(peak_date, ebb_end)
        dur = (ebb_end - ferment_start).days
        return {
            "industry": industry_name, "has_amount": has_amount,
            "发酵起点": ferment_start, "顶峰": peak_date, "退潮结束": ebb_end,
            "发酵期涨幅": ferment_ret, "退潮期跌幅": ebb_ret,
            "热度峰值": float(peak_val), "热度均值": float(mean_h),
            "持续天数": dur,
        }

    # ---------- 3. 板块轮动(量化) ----------
    def detect_rotation_chain(self, window=5, top_n=3):
        """精确轮动: 每5日TOP3 + 切换事件(退出行业后续跌幅/进入行业启动涨幅)"""
        if self.benchmark is None:
            return {"timeline": [], "switch_events": [], "rotation_chain": "", "summary": ""}
        all_dates = self.benchmark["date"].tolist()
        if len(all_dates) < window + 1:
            return {"timeline": [], "switch_events": [], "rotation_chain": "", "summary": ""}

        timeline = []
        for i in range(0, len(all_dates) - window + 1, window):
            s = all_dates[i]
            e = all_dates[min(i + window - 1, len(all_dates) - 1)]
            rets = {}
            for ind, df in self.index_data.items():
                r = self._ret_in_range(df, s, e)
                if not np.isnan(r):
                    rets[ind] = r
            if not rets:
                continue
            ranked = sorted(rets.items(), key=lambda x: -x[1])
            top = [(t[0], round(t[1], 1)) for t in ranked[:top_n]]
            bot = [(t[0], round(t[1], 1)) for t in ranked[-top_n:]]
            timeline.append({"window_start": s, "window_end": e,
                             "leaders": top, "laggards": bot})

        # 切换事件: TOP3 集合变化
        switch_events = []
        prev_top = set()
        for tw in timeline:
            cur_top = set(t[0] for t in tw["leaders"])
            if prev_top:
                exit_inds = prev_top - cur_top
                enter_inds = cur_top - prev_top
                if exit_inds or enter_inds:
                    exit_follow, enter_follow = {}, {}
                    for ind in exit_inds:
                        df = self.index_data.get(ind)
                        if df is not None:
                            r = self._ret_in_range(df, tw["window_start"],
                                                   tw["window_start"] + pd.Timedelta(days=14))
                            exit_follow[ind] = round(r, 1) if not np.isnan(r) else None
                    for ind in enter_inds:
                        df = self.index_data.get(ind)
                        if df is not None:
                            r = self._ret_in_range(df, tw["window_start"],
                                                   tw["window_start"] + pd.Timedelta(days=14))
                            enter_follow[ind] = round(r, 1) if not np.isnan(r) else None
                    switch_events.append({"date": tw["window_start"], "exit": list(exit_inds),
                                          "enter": list(enter_inds),
                                          "exit_follow": exit_follow, "enter_follow": enter_follow})
            prev_top = cur_top

        # 轮动链文本
        seq = []
        prev_leader = None
        for tw in timeline:
            leader = tw["leaders"][0][0] if tw["leaders"] else None
            if leader != prev_leader:
                seq.append((tw["window_start"], leader,
                            tw["leaders"][0][1] if tw["leaders"] else None))
                prev_leader = leader
        chain_text = " → ".join(f"{d.strftime('%m.%d')}[{l}({r:+.0f}%)]"
                                for d, l, r in seq[:8] if r is not None)
        n_switch = len([s for s in switch_events if s["enter"]])
        weeks = max(1, len(all_dates) // 5)
        speed = "快" if n_switch > weeks * 0.8 else ("慢" if n_switch < weeks * 0.3 else "中")
        summary = f"轮动{speed}速({n_switch}次切换/{weeks}周), " + \
                  (f"主线: {seq[0][1]}" if seq else "无明显主线")
        return {"timeline": timeline, "switch_events": switch_events,
                "rotation_chain": chain_text, "sequence": seq, "summary": summary}

    # ---------- 4. 热点主线 ----------
    def identify_hotspots(self, top_n=5):
        if self.rankings is None:
            self.calc_industry_rankings()
        rdf = self.rankings
        phases = self.phases or []
        phase_cols = [f"阶段{p['idx']}" for p in phases]
        # 每阶段TOP top_n
        top_in_phases = {c: set(rdf.nlargest(top_n, c)["行业"]) for c in phase_cols if c in rdf.columns}
        # 主线: 在多个阶段都进TOP
        from collections import Counter
        cnt = Counter()
        for c, s in top_in_phases.items():
            for ind in s:
                cnt[ind] += 1
        mains = [(ind, n) for ind, n in cnt.items() if n >= max(2, len(phases) // 2 + 1)]
        mains.sort(key=lambda x: -x[1])
        main_lines = []
        for ind, n in mains:
            cats = self.match_catalysts(ind)
            full = rdf.loc[rdf["行业"] == ind, "全期涨跌幅"]
            main_lines.append({
                "行业": ind, "持续阶段数": n,
                "总涨幅": float(full.iloc[0]) if len(full) else 0,
                "催化剂": cats[:3],
            })
        # 短期热点: 只在1个阶段TOP且全期排名靠前
        short = []
        for ind, n in cnt.items():
            if n == 1:
                cats = self.match_catalysts(ind)
                full = rdf.loc[rdf["行业"] == ind, "全期涨跌幅"]
                short.append({"行业": ind, "总涨幅": float(full.iloc[0]) if len(full) else 0, "催化剂": cats[:2]})
        short.sort(key=lambda x: -x["总涨幅"])
        # 持续低迷: 全期跌幅最大
        bottoms = rdf.nsmallest(5, "全期涨跌幅")[["行业", "全期涨跌幅"]]
        bottom_list = [{"行业": r["行业"], "跌幅": float(r["全期涨跌幅"])} for _, r in bottoms.iterrows()]
        return {"主线": main_lines, "短期热点": short[:5], "持续低迷": bottom_list}

    # ---------- 5. 临近板块联动 ----------
    def calc_lead_lag(self, industry_a, industry_b, max_lag=10):
        """行业A对B的领先-滞后: 交叉相关 corr(ret_A[t], ret_B[t+lag])"""
        da = self.index_data.get(industry_a)
        db = self.index_data.get(industry_b)
        if da is None or db is None:
            return None
        ra = da.set_index("date")["close"].astype(float).pct_change()
        rb = db.set_index("date")["close"].astype(float).pct_change()
        df = pd.concat([ra, rb], axis=1, keys=["a", "b"]).dropna()
        if len(df) < max_lag + 5:
            return None
        a, b = df["a"].values, df["b"].values
        best_lag, best_c = 0, -2
        for lag in range(-max_lag, max_lag + 1):
            if lag == 0:
                c = np.corrcoef(a, b)[0, 1]
            elif lag > 0:
                c = np.corrcoef(a[:-lag], b[lag:])[0, 1] if len(a) - lag > 2 else 0
            else:
                c = np.corrcoef(a[-lag:], b[:lag])[0, 1] if len(a) + lag > 2 else 0
            if not np.isnan(c) and abs(c) > abs(best_c):
                best_c, best_lag = c, lag
        lead = "领先" if best_lag > 0 else ("滞后" if best_lag < 0 else "同步")
        interp = f"{industry_a}{lead}{industry_b}约{abs(best_lag)}个交易日(corr={best_c:.2f})"
        return {"max_corr": float(best_c), "best_lag": int(best_lag),
                "interpretation": interp}

    def analyze_adjacent_sectors(self):
        results = {}
        for chain_name, members in INDUSTRY_CHAINS.items():
            avail = [m for m in members if m in self.index_data]
            if len(avail) < 2:
                results[chain_name] = {"成员": avail, "相关系数": None, "note": "成员不足"}
                continue
            rets = pd.DataFrame({m: self.index_data[m]["close"].astype(float).pct_change()
                                 for m in avail}).dropna(how="all")
            if len(rets) < 5:
                results[chain_name] = {"成员": avail, "相关系数": None, "note": "数据不足"}
                continue
            corr = rets.corr()
            mask = np.triu(np.ones(corr.shape, dtype=bool), 1)
            mean_corr = float(corr.values[mask].mean()) if mask.sum() else 0
            lead_lag = {}
            base = avail[0]
            for m in avail[1:]:
                ll = self.calc_lead_lag(base, m)
                lead_lag[m] = ll["best_lag"] if ll else 0
            results[chain_name] = {"成员": avail, "相关系数": round(mean_corr, 2),
                                   "base": base, "领先滞后(日)": lead_lag}
        return results

    # ---------- 6. 周期叠加 ----------
    def overlay_cycle_phase(self):
        rows = []
        for ind in self.index_data:
            sub = self.cycles[self.cycles["行业名称"].astype(str) == ind].copy()
            sub["s"] = pd.to_datetime(sub["起始日期"].astype(str).apply(_norm_date), errors="coerce")
            sub["e"] = pd.to_datetime(sub["结束日期"].astype(str).apply(_norm_date), errors="coerce")
            # 落在时间窗口内的段
            hit = sub[(sub["e"] >= self.start) & (sub["s"] <= self.end)]
            phases_hit = [str(r["周期阶段_标准化"]) for _, r in hit.iterrows()]
            devs = [str(r["deviation_type"]) for _, r in hit.iterrows() if pd.notna(r.get("deviation_type"))]
            transition = ""
            if len(set(phases_hit)) > 1:
                transition = " → ".join(phases_hit)
            excess = None
            if self.backtest_summary is not None and ind in self.backtest_summary.index:
                excess = float(self.backtest_summary.loc[ind, "binary_超额年化"])
            rows.append({
                "行业": ind, "阶段": phases_hit[0] if phases_hit else "?",
                "阶段转换": transition, "deviation": ";".join(devs),
                "回测超额%": excess,
            })
        return pd.DataFrame(rows)

    # ---------- 7. 催化剂匹配 ----------
    def match_catalysts(self, industry_name=None):
        if self.catalysts is None or len(self.catalysts) == 0:
            return []
        if industry_name is None:
            return [{"date": str(r["date"].date()), "event": r["event_name"],
                     "type": r["event_type"], "direction": r["direction"],
                     "importance": r["importance"]}
                    for _, r in self.catalysts.iterrows()]
        out = []
        for _, r in self.catalysts.iterrows():
            rel = str(r["related_industries"])
            if industry_name in rel or "全行业" in rel:
                out.append({"date": str(r["date"].date()), "event": r["event_name"],
                            "direction": r["direction"], "importance": r["importance"]})
        return out

    # ---------- 叙事报告 ----------
    def generate_narrative(self):
        if self.phases is None:
            self.detect_market_phases()
        if self.rankings is None:
            self.calc_industry_rankings()
        hot = self.identify_hotspots()
        chains = self.analyze_adjacent_sectors()
        cycle = self.overlay_cycle_phase()
        rotation = self.detect_rotation_chain()

        # 大盘涨跌
        bench_ret = (self.benchmark["close"].iloc[-1] / self.benchmark["close"].iloc[0] - 1) * 100 \
            if self.benchmark is not None and len(self.benchmark) else 0

        lines = []
        lines.append(f"# {self.label} 市场复盘报告\n")
        lines.append("## 一、大盘走势概览")
        lines.append(f"- 时间窗口: {self.start.date()} ~ {self.end.date()}")
        lines.append(f"- 大盘(上证指数)涨跌幅: **{bench_ret:+.2f}%**")
        lines.append(f"- 市场分为 **{len(self.phases)}** 个阶段:")
        for ph in self.phases:
            vol = ph.get("vol_label", ph["type"])
            cat_str = ""
            if ph.get("catalyst"):
                cat_str = " | 催化: " + "; ".join(c["event"][:12] for c in ph["catalyst"][:2])
            lines.append(f"  - 阶段{ph['idx']}({ph['start'].date()}~{ph['end'].date()}): "
                         f"**{vol}** {ph['return']:+.2f}%, {ph['days']}天{cat_str}")

        lines.append("\n## 二、行业涨跌幅全景")
        rdf = self.rankings.sort_values("全期涨跌幅", ascending=False)
        top5 = rdf.head(5)
        bot5 = rdf.tail(5)
        lines.append(f"- 领涨TOP5: " + ", ".join(f"{r['行业']}({r['全期涨跌幅']:+.1f}%)" for _, r in top5.iterrows()))
        lines.append(f"- 领跌BOTTOM5: " + ", ".join(f"{r['行业']}({r['全期涨跌幅']:+.1f}%)" for _, r in bot5.iterrows()))

        lines.append("\n## 三、热点主线分析")
        if hot["主线"]:
            for ml in hot["主线"]:
                cats = "; ".join(f"{c['date']} {c['event']}" for c in ml["催化剂"]) if ml["催化剂"] else "无明确催化"
                lines.append(f"### 主线: {ml['行业']}")
                lines.append(f"- 持续阶段数: {ml['持续阶段数']}, 全期涨幅: {ml['总涨幅']:+.1f}%")
                lines.append(f"- 催化剂: {cats}")
                # 热度周期
                hc = self.detect_heat_cycle(ml["行业"])
                if hc:
                    lines.append(f"- 热度周期: 发酵{hc['发酵起点'].date()} → "
                                 f"顶峰{hc['顶峰'].date()}(热度峰值{hc['热度峰值']:.3f}) → "
                                 f"退潮{hc['退潮结束'].date()}")
                    lines.append(f"- 发酵期涨幅 {hc['发酵期涨幅']:+.1f}%, 退潮期跌幅 {hc['退潮期跌幅']:+.1f}%, "
                                 f"持续{hc['持续天数']}天")
        else:
            lines.append("(无明显贯穿多阶段的主线)")
        if hot["短期热点"]:
            lines.append("\n### 短期热点")
            for sh in hot["短期热点"][:3]:
                lines.append(f"- {sh['行业']}: {sh['总涨幅']:+.1f}%")

        lines.append("\n## 四、板块轮动路径")
        if rotation and rotation.get("rotation_chain"):
            lines.append(f"- 轮动链: {rotation['rotation_chain']}")
            lines.append(f"- {rotation['summary']}")
            # 切换事件
            sev = [s for s in rotation.get("switch_events", []) if s["enter"]]
            if sev:
                lines.append(f"- 切换事件({len(sev)}次):")
                for s in sev[:5]:
                    enter_s = ", ".join(f"{k}({v:+.0f}%)" for k, v in s["enter_follow"].items() if v is not None)
                    exit_s = ", ".join(f"{k}({v:+.0f}%)" for k, v in s["exit_follow"].items() if v is not None)
                    lines.append(f"  - {s['date'].date()}: 退出[{exit_s}] ← 进入[{enter_s}]")
        else:
            lines.append("- (数据不足以识别轮动)")

        lines.append("\n## 五、产业链联动")
        for cname, info in chains.items():
            if info.get("相关系数") is None:
                continue
            ll = info.get("领先滞后(日)", {})
            ll_str = ", ".join(f"{k}({'领先' if v>0 else '滞后' if v<0 else '同步'}{abs(v)}日)" for k, v in ll.items()) if ll else ""
            lines.append(f"- {cname}: 平均相关 {info['相关系数']:.2f} ({'联动紧密' if info['相关系数']>0.6 else '中等' if info['相关系数']>0.4 else '较弱'}); {ll_str}")

        lines.append("\n## 六、催化剂时间线")
        cats = self.match_catalysts()
        if cats:
            for c in cats:
                lines.append(f"- {c['date']} [{c['type']}/{c['direction']}/重要{c['importance']}] {c['event']}")
        else:
            lines.append("(时间窗口内无催化剂事件)")

        lines.append("\n## 七、产能周期视角")
        for _, r in cycle.iterrows():
            ex = f" 超额{r['回测超额%']:+.1f}%" if r['回测超额%'] is not None and not np.isnan(r['回测超额%']) else ""
            lines.append(f"- {r['行业']}: {r['阶段']}{' → '+r['阶段转换'] if r['阶段转换'] else ''}"
                         f"{' ['+r['deviation']+']' if r['deviation'] else ''}{ex}")

        lines.append("\n## 八、关键发现")
        findings = self.generate_insights(bench_ret, hot, rdf, cycle, rotation)
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. {f}")
        return "\n".join(lines)

    def generate_insights(self, bench_ret, hot, rdf, cycle, rotation=None):
        """5条规则驱动的自动洞察"""
        f = []
        top3_sum = rdf.head(3)["全期涨跌幅"].sum()
        median = rdf["全期涨跌幅"].median()
        if median != 0 and abs(top3_sum / median) > 5:
            f.append(f"市场主线高度集中: TOP3行业涨幅合计{top3_sum:+.1f}%, 远超中位数{median:+.1f}%。")
        if rotation:
            sev = [s for s in rotation.get("switch_events", []) if s["enter"]]
            weeks = max(1, len(self.benchmark) // 5) if self.benchmark is not None else 1
            if sev:
                rate = len(sev) / weeks
                tag = "主线持续性弱" if rate > 0.8 else ("主线较稳定" if rate < 0.3 else "")
                speed_word = rotation['summary'].split("速")[0].replace("轮动", "")
                f.append(f"轮动{speed_word}速, {len(sev)}次主线切换/{weeks}周{('，'+tag) if tag else ''}。")
        bull = cycle[cycle["阶段"].isin(["成长期", "复苏期"])]
        consistent, total = 0, 0
        for _, r in rdf.iterrows():
            ph = cycle.loc[cycle["行业"] == r["行业"], "阶段"]
            ph = ph.iloc[0] if len(ph) else None
            if ph in ("成长期", "复苏期") and r["全期涨跌幅"] > 0:
                consistent += 1; total += 1
            elif ph in ("过剩期", "出清期") and r["全期涨跌幅"] < 0:
                consistent += 1; total += 1
            elif ph:
                total += 1
        if total:
            rate = consistent / total * 100
            note = "周期框架解释力强" if rate >= 70 else "本期由催化剂/主题驱动，周期解释力较弱"
            f.append(f"产能周期一致率 {rate:.0f}%({consistent}/{total}), {note}。")
        cat_eff = self._catalyst_effectiveness()
        if cat_eff:
            best = cat_eff[0]
            f.append(f"最有效催化剂: {best['event']}({best['date']}), 关联行业事件后5日平均{best['avg_ret']:+.1f}%。")
        if rotation:
            for s in rotation.get("switch_events", []):
                ent = [(k, v) for k, v in s["enter_follow"].items() if v and v > 3]
                if ent:
                    f.append(f"{s['date'].date()}前后资金切换信号, 流向{ent[0][0]}(启动+{ent[0][1]:.0f}%)。")
                    break
        return f[:5]

    def _catalyst_effectiveness(self, days=5):
        if self.catalysts is None or len(self.catalysts) == 0:
            return []
        out = []
        for _, c in self.catalysts.iterrows():
            rel = str(c["related_industries"])
            inds = INDUSTRIES_22 if "全行业" in rel else [i for i in rel.split(";") if i in self.index_data]
            rets = []
            for ind in inds:
                if ind not in self.index_data:
                    continue
                df = self.index_data[ind]
                after = df[df["date"] >= c["date"]].head(days + 1)
                if len(after) >= 2:
                    rets.append((after["close"].iloc[-1] / after["close"].iloc[0] - 1) * 100)
            if rets:
                out.append({"date": str(c["date"].date()), "event": c["event_name"],
                            "avg_ret": float(np.mean(rets)), "n": len(rets)})
        out.sort(key=lambda x: -x["avg_ret"])
        return out

    # ---------- 终端输出 ----------
    def print_terminal(self):
        if self.phases is None:
            self.detect_market_phases()
        if self.rankings is None:
            self.calc_industry_rankings()
        print("=" * 78)
        print(f"  📈 {self.label} 市场复盘  ({self.start.date()} ~ {self.end.date()})")
        print("=" * 78)
        if self.benchmark is not None and len(self.benchmark):
            br = (self.benchmark["close"].iloc[-1] / self.benchmark["close"].iloc[0] - 1) * 100
            print(f"大盘(上证): {br:+.2f}%  |  阶段数: {len(self.phases)}")
            circ = "①②③④⑤⑥⑦⑧⑨⑩"
            for ph in self.phases:
                vol = ph.get("vol_label", ph["type"])
                cat = ""
                if ph.get("catalyst"):
                    cat = " | " + "; ".join(c["event"][:14] for c in ph["catalyst"][:2])
                mark = circ[ph['idx']-1] if ph['idx'] <= 10 else f"阶段{ph['idx']}"
                print(f"  {mark} {ph['start'].strftime('%m.%d')}~{ph['end'].strftime('%m.%d')} "
                      f"[{vol}] {ph['return']:+.2f}% ({ph['days']}天){cat}")
        rdf = self.rankings
        print(f"\n📈 行业 TOP5: " + " > ".join(f"{r['行业']}({r['全期涨跌幅']:+.1f}%)"
                                              for _, r in rdf.head(5).iterrows()))
        print(f"📉 行业 BOTTOM5: " + " < ".join(f"{r['行业']}({r['全期涨跌幅']:+.1f}%)"
                                                for _, r in rdf.tail(5).iterrows()))
        # 热点 + 热度
        hot = self.identify_hotspots()
        if hot["主线"]:
            print(f"\n🔥 热点主线:")
            for m in hot["主线"]:
                hc = self.detect_heat_cycle(m["行业"])
                hp = f" 发酵{hc['发酵起点'].strftime('%m.%d')}→顶峰{hc['顶峰'].strftime('%m.%d')}→退潮{hc['退潮结束'].strftime('%m.%d')}" if hc else ""
                print(f"   {m['行业']}({m['总涨幅']:+.1f}%,{m['持续阶段数']}阶段){hp}")
        # 轮动
        rot = self.detect_rotation_chain()
        if rot and rot.get("rotation_chain"):
            print(f"\n🔄 轮动链: {rot['rotation_chain']}")
            print(f"   {rot['summary']}")
            sev = [s for s in rot.get("switch_events", []) if s["enter"]]
            for s in sev[:3]:
                ent = ", ".join(f"{k}({v:+.0f}%)" for k, v in s["enter_follow"].items() if v is not None)
                exi = ", ".join(f"{k}({v:+.0f}%)" for k, v in s["exit_follow"].items() if v is not None)
                print(f"   切换 {s['date'].strftime('%m.%d')}: [{exi}] → [{ent}]")
        # 产业链
        chains = self.analyze_adjacent_sectors()
        tight = [(k, v) for k, v in chains.items() if v.get("相关系数") and v["相关系数"] > 0.5]
        if tight:
            print(f"\n🔗 产业链联动(相关>0.5):")
            for k, v in sorted(tight, key=lambda x: -x[1]["相关系数"])[:4]:
                ll = v.get("领先滞后(日)", {})
                ll_s = ", ".join(f"{m}{'领先' if d>0 else '滞后' if d<0 else '同步'}{abs(d)}日"
                                 for m, d in ll.items() if d != 0)
                print(f"   {k}: 相关{v['相关系数']:.2f} {ll_s}")
        # 催化剂
        cats = self.match_catalysts()
        print(f"\n💡 催化剂: 窗口内 {len(cats)} 条事件")
        for c in cats[:4]:
            print(f"   {c['date']} [{c['direction']}] {c['event']}")
        # 关键发现
        cycle = self.overlay_cycle_phase()
        bench_ret = (self.benchmark["close"].iloc[-1] / self.benchmark["close"].iloc[0] - 1) * 100 \
            if self.benchmark is not None and len(self.benchmark) else 0
        insights = self.generate_insights(bench_ret, hot, rdf, cycle, rot)
        if insights:
            print(f"\n🎯 关键发现:")
            for i, ins in enumerate(insights, 1):
                print(f"   {i}. {ins}")

    # ---------- HTML ----------
    def generate_html(self):
        os.makedirs(REPORT_DIR, exist_ok=True)
        os.makedirs(CHART_DIR, exist_ok=True)
        narrative = self.generate_narrative()
        # 尝试生成图表
        chart_paths = {}
        try:
            import replay_charts as rc
            chart_paths = rc.generate_all(self)
        except Exception as e:
            chart_paths = {"error": str(e)}

        def img_tag(key, cap):
            p = chart_paths.get(key)
            if p and os.path.exists(p):
                import base64
                with open(p, "rb") as f:
                    b = base64.b64encode(f.read()).decode()
                return f"<h3>{cap}</h3><img src='data:image/png;base64,{b}' style='width:100%;max-width:1000px'>"
            return f"<h3>{cap}</h3><p style='color:#999'>(图表生成失败)</p>"

        html = [f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>{self.label} 市场复盘</title>
<style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;max-width:1100px;margin:auto;padding:24px;line-height:1.7;color:#222}}
h1{{color:#1a3a5c;border-bottom:3px solid #1a3a5c;padding-bottom:8px}}
h2{{color:#1a3a5c;margin-top:28px;border-left:4px solid #0969da;padding-left:10px}}
pre{{background:#f6f8fa;padding:16px;border-radius:6px;white-space:pre-wrap;font-size:14px}}
img{{border:1px solid #ddd;border-radius:4px;margin:8px 0}}
</style></head><body>
<h1>📈 {self.label} 市场复盘报告</h1>
"""]
        # 叙事(markdown转简易)
        import re as _re
        # 简单渲染: ## -> h2, ** -> b, - -> li
        lines = narrative.split("\n")
        out = []
        in_list = False
        for ln in lines:
            if ln.startswith("# "):
                out.append(f"<h1>{ln[2:]}</h1>"); continue
            if ln.startswith("## "):
                if in_list: out.append("</ul>"); in_list = False
                out.append(f"<h2>{ln[3:]}</h2>"); continue
            if ln.startswith("### "):
                if in_list: out.append("</ul>"); in_list = False
                out.append(f"<h3>{ln[4:]}</h3>"); continue
            if ln.startswith("- "):
                if not in_list: out.append("<ul>"); in_list = True
                txt = ln[2:].replace("**", "<b>", 1).replace("**", "</b>", 1)
                out.append(f"<li>{txt}</li>"); continue
            if ln.strip() == "":
                if in_list: out.append("</ul>"); in_list = False
                out.append(""); continue
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<p>{ln}</p>")
        if in_list: out.append("</ul>")
        html.append("\n".join(out))

        html.append("<hr><h2>📊 图表分析</h2>")
        html.append(img_tag("chart1", "图1: 大盘走势 + 阶段划分"))
        html.append(img_tag("chart2", "图2: 22行业涨跌幅热力图(各阶段)"))
        html.append(img_tag("chart3", "图3: 热点主线净值曲线"))
        html.append(img_tag("chart4", "图4: 板块轮动甘特图(含切换标注+大盘参照)"))
        html.append(img_tag("chart5", "图5: 22行业相关系数热力图(产业链联动)"))

        # 行业排名表
        if self.rankings is not None:
            html.append("<h2>📋 行业排名明细</h2><table border='1' cellpadding='5' style='border-collapse:collapse;font-size:13px'><tr><th>排名</th><th>行业</th><th>全期涨跌</th>")
            for ph in (self.phases or []):
                html.append(f"<th>阶段{ph['idx']}</th>")
            html.append("</tr>")
            for _, r in self.rankings.sort_values("全期涨跌幅", ascending=False).iterrows():
                html.append(f"<tr><td>{r['全期排名']}</td><td>{r['行业']}</td>"
                            f"<td style='color:{'#1a7f37' if r['全期涨跌幅']>=0 else '#cf222e'}'>{r['全期涨跌幅']:+.1f}%</td>")
                for ph in (self.phases or []):
                    col = f"阶段{ph['idx']}"
                    v = r.get(col)
                    html.append(f"<td style='color:{'#1a7f37' if (v or 0)>=0 else '#cf222e'}'>{v:+.1f}%</td>" if not np.isnan(v) else "<td>-</td>")
                html.append("</tr>")
            html.append("</table>")
        html.append("</body></html>")

        out_path = os.path.join(REPORT_DIR, f"{self.label}_replay.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html))
        return out_path

    # ===== 31行业全量 / 季度总览 / 主线切换 分析 =====

    def load_sw31_data(self):
        """加载31行业全量数据"""
        sw31_path = os.path.join(self.base_dir, "raw_data", "sw31_daily", "sw31_daily_all.csv")
        if os.path.exists(sw31_path):
            self.sw31_df = pd.read_csv(sw31_path, parse_dates=["日期"])
            self.sw31_industries = sorted(self.sw31_df["行业名称"].unique().tolist())
            self.use_sw31 = True
            print(f"  ✅ 31行业全量表: {len(self.sw31_df)}行, "
                  f"{len(self.sw31_industries)}行业, "
                  f"{self.sw31_df['日期'].min().strftime('%Y-%m-%d')} ~ "
                  f"{self.sw31_df['日期'].max().strftime('%Y-%m-%d')}")
        else:
            self.sw31_df = None
            self.sw31_industries = []
            self.use_sw31 = False
            print(f"  ⚠️ 31行业全量表不存在，降级使用22行业数据")

    def load_full_catalysts(self):
        """加载完整催化剂事件库"""
        full_path = os.path.join(self.base_dir, "raw_data", "catalyst_events_full.csv")
        if os.path.exists(full_path):
            self.catalysts_full = pd.read_csv(full_path, parse_dates=["日期"])
            print(f"  ✅ 催化剂事件库: {len(self.catalysts_full)}条 "
                  f"({self.catalysts_full['日期'].min().strftime('%Y-%m-%d')} ~ "
                  f"{self.catalysts_full['日期'].max().strftime('%Y-%m-%d')})")
        else:
            self.catalysts_full = self.catalysts
            print(f"  ⚠️ 完整催化剂库不存在，使用原有{len(self.catalysts)}条")

    def generate_quarterly_overview(self):
        """生成2015Q1~当前季度的全行业季度涨跌幅总览"""
        df = self.sw31_df if getattr(self, "use_sw31", False) else self._build_22_industry_df()
        if df is None or df.empty:
            return None, "无数据"
        df = df.copy()
        df["季度"] = df["日期"].dt.to_period("Q").astype(str)
        quarters = sorted(df["季度"].unique())
        industries = sorted(df["行业名称"].unique())
        rows = []
        for q in quarters:
            q_df = df[df["季度"] == q]
            for ind in industries:
                ind_df = q_df[q_df["行业名称"] == ind].sort_values("日期")
                if len(ind_df) < 2:
                    continue
                open_price = ind_df.iloc[0]["开盘"]
                close_price = ind_df.iloc[-1]["收盘"]
                q_return = (close_price - open_price) / open_price * 100 if open_price > 0 else 0.0
                amount_col = next((c for c in ["成交额_亿元", "成交额", "amount"] if c in ind_df.columns), None)
                q_amount = ind_df[amount_col].sum() if amount_col else 0.0
                rows.append({"季度": q, "行业名称": ind,
                             "季度涨跌幅_pct": round(q_return, 2),
                             "季度成交额_亿": round(q_amount, 2),
                             "交易日数": len(ind_df),
                             "季初价": round(open_price, 2), "季末价": round(close_price, 2)})
        result = pd.DataFrame(rows)
        result["季度排名"] = result.groupby("季度")["季度涨跌幅_pct"].rank(ascending=False).astype(int)
        q_totals = result.groupby("季度")["季度成交额_亿"].transform("sum")
        result["成交额占比_pct"] = (result["季度成交额_亿"] / q_totals * 100).round(2)
        # 匹配催化剂
        cats = getattr(self, "catalysts_full", None)
        if cats is None or (hasattr(cats, "empty") and cats.empty):
            cats = self.catalysts
        if cats is not None and not cats.empty:
            result["匹配催化剂"] = ""
            for q in quarters:
                year = int(q[:4]); qn = int(q[5:].replace("Q", ""))
                q_start = pd.Timestamp(year, (qn - 1) * 3 + 1, 1)
                q_end = q_start + pd.offsets.QuarterEnd(0)
                q_cats = cats[(cats["日期"] >= q_start) & (cats["日期"] <= q_end)]
                if q_cats.empty:
                    continue
                for _, cat_row in q_cats.iterrows():
                    related = str(cat_row.get("关联行业", cat_row.get("related_industries", "全行业")))
                    event_name = str(cat_row.get("事件名称", cat_row.get("event_name", "")))
                    if related == "全行业":
                        mask = result["季度"] == q
                    else:
                        related_list = [x.strip() for x in related.split(";")]
                        mask = (result["季度"] == q) & (result["行业名称"].isin(related_list))
                    for i in result[mask].index:
                        existing = result.at[i, "匹配催化剂"]
                        result.at[i, "匹配催化剂"] = (existing + "; " if existing else "") + event_name
        summary_lines = [
            f"季度总览: {quarters[0]} ~ {quarters[-1]} ({len(quarters)}个季度 × {len(industries)}个行业)",
            f"总数据行: {len(result)}", "",
            "── 每季度 TOP3 / BOTTOM3 ──"]
        for q in quarters:
            q_data = result[result["季度"] == q].sort_values("季度排名")
            if q_data.empty:
                continue
            top3 = q_data.head(3)
            bot3 = q_data.tail(3).sort_values("季度排名", ascending=False)
            top_str = ", ".join(f"{r['行业名称']}({r['季度涨跌幅_pct']:+.1f}%)" for _, r in top3.iterrows())
            bot_str = ", ".join(f"{r['行业名称']}({r['季度涨跌幅_pct']:+.1f}%)" for _, r in bot3.iterrows())
            summary_lines.append(f"  {q}: TOP [{top_str}]  BOT [{bot_str}]")
        return result, "\n".join(summary_lines)

    def detect_mainline_switch(self):
        """识别主线切换事件：连续≥2周TOP3为主线，旧主线退出+新主线进入为切换"""
        df = self.sw31_df if getattr(self, "use_sw31", False) else self._build_22_industry_df()
        if df is None or df.empty:
            return None, "无数据"
        df = df.copy().sort_values(["日期", "行业名称"])
        df["周"] = df["日期"].dt.to_period("W").astype(str)
        weekly_returns = []
        for (week, ind), g in df.groupby(["周", "行业名称"]):
            g = g.sort_values("日期")
            if len(g) < 1:
                continue
            open_p = g.iloc[0]["开盘"]; close_p = g.iloc[-1]["收盘"]
            ret = (close_p - open_p) / open_p * 100 if open_p > 0 else 0
            amount_col = next((c for c in ["成交额_亿元", "成交额", "amount"] if c in g.columns), None)
            amt = g[amount_col].sum() if amount_col else 0
            weekly_returns.append({"周": week, "行业名称": ind,
                                   "周涨跌幅_pct": round(ret, 2), "周成交额": round(amt, 2),
                                   "周起始日": g["日期"].min(), "周结束日": g["日期"].max()})
        wr = pd.DataFrame(weekly_returns)
        wr["周排名"] = wr.groupby("周")["周涨跌幅_pct"].rank(ascending=False).astype(int)
        wr["是TOP3"] = wr["周排名"] <= 3
        weeks = sorted(wr["周"].unique())
        mainline_periods = []
        for ind in sorted(wr["行业名称"].unique()):
            ind_data = wr[wr["行业名称"] == ind].sort_values("周")
            streak_start = None; streak_weeks = []
            for _, row in ind_data.iterrows():
                if row["是TOP3"]:
                    if streak_start is None:
                        streak_start = row["周"]
                    streak_weeks.append(row)
                else:
                    if streak_start and len(streak_weeks) >= 2:
                        mainline_periods.append(self._mk_mainline(ind, streak_weeks))
                    streak_start = None; streak_weeks = []
            if streak_start and len(streak_weeks) >= 2:
                mainline_periods.append(self._mk_mainline(ind, streak_weeks))
        mp_df = pd.DataFrame(mainline_periods)
        if mp_df.empty:
            return mp_df, "未检测到主线"
        mp_df = mp_df.sort_values("起始日").reset_index(drop=True)
        switch_events = []
        for i in range(1, len(mp_df)):
            prev = mp_df.iloc[i - 1]; curr = mp_df.iloc[i]
            gap_days = (curr["起始日"] - prev["结束日"]).days
            if gap_days <= 35 and prev["行业名称"] != curr["行业名称"]:
                cats = getattr(self, "catalysts_full", None)
                if cats is None or (hasattr(cats, "empty") and cats.empty):
                    cats = self.catalysts
                matched_cats = []
                if cats is not None and not cats.empty:
                    cat_window = cats[(cats["日期"] >= prev["结束日"] - pd.Timedelta(days=7)) &
                                      (cats["日期"] <= curr["起始日"] + pd.Timedelta(days=7))]
                    for _, c in cat_window.iterrows():
                        related = str(c.get("关联行业", c.get("related_industries", "")))
                        if curr["行业名称"] in related or "全行业" in related:
                            matched_cats.append(str(c.get("事件名称", c.get("event_name", ""))))
                switch_events.append({"切换日期": curr["起始日"].strftime("%Y-%m-%d"),
                                      "旧主线": prev["行业名称"], "旧主线持续周数": prev["持续周数"],
                                      "旧主线累计涨幅_pct": round(prev["累计涨幅_pct"], 2),
                                      "旧主线结束日": prev["结束日"].strftime("%Y-%m-%d"),
                                      "新主线": curr["行业名称"],
                                      "新主线累计涨幅_pct": round(curr["累计涨幅_pct"], 2),
                                      "间隔天数": gap_days,
                                      "催化剂": "; ".join(matched_cats) if matched_cats else ""})
        switch_df = pd.DataFrame(switch_events)
        summary_lines = [f"主线识别: {len(mp_df)}段主线 (≥2周连续TOP3)",
                         f"切换事件: {len(switch_df)}次", "",
                         "── 主线列表 (TOP15 by 持续周数) ──"]
        for _, m in mp_df.nlargest(15, "持续周数").iterrows():
            summary_lines.append(f"  {m['行业名称']:6s} | {m['起始日'].strftime('%Y-%m-%d')} ~ "
                                 f"{m['结束日'].strftime('%Y-%m-%d')} | {m['持续周数']}周 | "
                                 f"{m['累计涨幅_pct']:+.1f}%")
        if not switch_df.empty:
            summary_lines += ["", "── 切换事件 (最近20次) ──"]
            for _, s in switch_df.tail(20).iterrows():
                cat_str = f" [{s['催化剂'][:30]}]" if s['催化剂'] else ""
                summary_lines.append(f"  {s['切换日期']} {s['旧主线']}→{s['新主线']} "
                                     f"(旧{s['旧主线累计涨幅_pct']:+.1f}%, 新{s['新主线累计涨幅_pct']:+.1f}%){cat_str}")
        return (mp_df, switch_df), "\n".join(summary_lines)

    @staticmethod
    def _mk_mainline(ind, streak_weeks):
        return {"行业名称": ind, "起始周": streak_weeks[0]["周"],
                "结束周": streak_weeks[-1]["周"],
                "起始日": streak_weeks[0]["周起始日"], "结束日": streak_weeks[-1]["周结束日"],
                "持续周数": len(streak_weeks),
                "累计涨幅_pct": sum(w["周涨跌幅_pct"] for w in streak_weeks)}

    def cross_period_comparison(self, industry_name=None):
        """同类主线切换横向对比"""
        result = self.detect_mainline_switch()
        if result[0] is None:
            return None, "无数据"
        mp_df, switch_df = result[0]
        if switch_df.empty:
            return None, "无切换事件"
        if industry_name:
            filtered = switch_df[switch_df["新主线"] == industry_name]
            if filtered.empty:
                return None, f"未找到{industry_name}作为新主线的切换"
            summary = (f"'{industry_name}' 作为新主线共出现 {len(filtered)} 次\n"
                       f"平均累计涨幅: {filtered['新主线累计涨幅_pct'].mean():.1f}%\n"
                       f"平均间隔天数: {filtered['间隔天数'].mean():.0f}天")
            return filtered, summary
        stats = []
        for ind in switch_df["新主线"].unique():
            s = switch_df[switch_df["新主线"] == ind]
            stats.append({"行业名称": ind, "成为新主线次数": len(s),
                          "平均累计涨幅_pct": round(s["新主线累计涨幅_pct"].mean(), 2),
                          "最大累计涨幅_pct": round(s["新主线累计涨幅_pct"].max(), 2)})
        stats_df = pd.DataFrame(stats).sort_values("成为新主线次数", ascending=False)
        summary = f"主线切换统计 ({len(switch_df)}次切换, {len(stats_df)}个行业曾为主线)\n"
        for _, s in stats_df.head(10).iterrows():
            summary += (f"  {s['行业名称']:6s}: {s['成为新主线次数']}次, "
                        f"平均涨幅{s['平均累计涨幅_pct']:+.1f}%, 最大涨幅{s['最大累计涨幅_pct']:+.1f}%\n")
        return stats_df, summary

    def _build_22_industry_df(self):
        """将现有22行业数据转为统一格式(降级方案)"""
        index_dir = os.path.join(self.base_dir, "raw_data", "index_daily")
        if not os.path.isdir(index_dir):
            return None
        dfs = []
        for f in os.listdir(index_dir):
            if not f.endswith(".csv") or f in ("上证指数.csv", "沪深300.csv", "创业板指.csv"):
                continue
            try:
                d = pd.read_csv(os.path.join(index_dir, f))
                name = f.replace(".csv", "")
                d["行业名称"] = name
                d["日期"] = pd.to_datetime(d["date"], errors="coerce")
                d = d.rename(columns={"open": "开盘", "close": "收盘",
                                      "high": "最高", "low": "最低",
                                      "amount": "成交额_亿元", "volume": "成交量_亿股"})
                dfs.append(d)
            except Exception:
                pass
        return pd.concat(dfs, ignore_index=True) if dfs else None

    def save_quarterly_overview(self, output_dir=None):
        """保存季度总览到CSV"""
        if output_dir is None:
            output_dir = os.path.join(self.base_dir, "raw_data")
        result, summary = self.generate_quarterly_overview()
        if result is None:
            print(summary); return
        csv_path = os.path.join(output_dir, "quarterly_overview.csv")
        result.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"✅ 季度总览CSV: {csv_path} ({len(result)}行)")
        print(summary)
        return result

    def save_mainline_analysis(self, output_dir=None):
        """保存主线分析到CSV"""
        if output_dir is None:
            output_dir = os.path.join(self.base_dir, "raw_data")
        result, summary = self.detect_mainline_switch()
        if result is None:
            print(summary); return
        mp_df, switch_df = result
        mp_path = os.path.join(output_dir, "mainline_periods.csv")
        mp_df.to_csv(mp_path, index=False, encoding="utf-8-sig")
        print(f"✅ 主线列表CSV: {mp_path} ({len(mp_df)}行)")
        if not switch_df.empty:
            sw_path = os.path.join(output_dir, "mainline_switches.csv")
            switch_df.to_csv(sw_path, index=False, encoding="utf-8-sig")
            print(f"✅ 切换事件CSV: {sw_path} ({len(switch_df)}行)")
        print(summary)
        return mp_df, switch_df


if __name__ == "__main__":
    w = sys.argv[1] if len(sys.argv) > 1 else "2025Q1"
    s, e = parse_time_window(w)
    mr = MarketReplay(BASE_DIR, s, e, label=w)
    mr.load_data()
    mr.print_terminal()
