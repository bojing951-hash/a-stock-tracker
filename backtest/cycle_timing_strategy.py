#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产能周期择时策略回测 (阶段2)
================================================
核心假说：行业在"成长期"和"复苏期"超额收益为正，在"过剩期"和"出清期"超额收益为负。
据此构建择时策略：成长/复苏满仓，过剩/出清空仓，景气顶部减半仓。

类: CycleTimingBacktest
  - 数据加载：industry_cycle.csv 周期标注 + index_daily/{行业}.csv 日线
  - 每日阶段标注：周期阶段_标准化 + deviation_type
  - 三种信号模式：binary / aggressive / conservative
  - 净值计算：策略仓位 × 日收益率复利
  - 绩效：年化/最大回撤/夏普/Calmar/胜率/分周期段拆解
"""
import os
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CYCLE_CSV = os.path.join(BASE_DIR, "raw_data", "industry_cycle.csv")
INDEX_DIR = os.path.join(BASE_DIR, "raw_data", "index_daily")

RF_ANNUAL = 0.025          # 无风险利率年化 2.5%
TRADING_DAYS = 252

# ---------- 阶段 -> 仓位 映射 ----------
POSITION_RULES = {
    "binary": {
        "成长期": 1.0, "复苏期": 1.0,
        "景气顶部": 0.5,
        "成熟稳定期": 0.75,
        "过剩期": 0.0, "出清期": 0.0,
    },
    "aggressive": {
        "成长期": 1.0,
        "复苏期": 0.5, "景气顶部": 0.5,
        "成熟稳定期": 0.0, "过剩期": 0.0, "出清期": 0.0,
    },
    "conservative": {
        "成长期": 1.0, "复苏期": 1.0, "成熟稳定期": 1.0, "景气顶部": 1.0,
        "过剩期": 0.0, "出清期": 0.0,
    },
}


class CycleTimingBacktest:
    def __init__(self, industry_name, cycle_csv_path=CYCLE_CSV,
                 index_csv_path=None):
        self.industry = industry_name
        self.cycle_csv_path = cycle_csv_path
        self.index_csv_path = index_csv_path or os.path.join(
            INDEX_DIR, f"{industry_name}.csv")

        self.cycles = self._load_cycles()
        self.prices = self._load_prices()
        self.labeled = None        # 标注阶段后的日线
        self.phase_segments = None  # 含/不含数据的周期段拆解

    # ---------- 1a. 数据加载 ----------
    @staticmethod
    def _norm_dates(series):
        """规范化日期字符串：
        '至今' -> 今天；'2022-11' -> '2022-11-01'；'YYYY-MM-DD' 不变。"""
        from datetime import datetime
        today = datetime(2026, 6, 21).strftime("%Y-%m-%d")
        out = []
        for v in series.astype(str):
            v = v.strip()
            if v in ("至今", "至今)", "nan", "") or "至今" in v:
                out.append(today)
            elif len(v) == 7:  # YYYY-MM
                out.append(f"{v}-01")
            else:
                out.append(v)
        return out

    def _load_cycles(self):
        df = pd.read_csv(self.cycle_csv_path)
        df = df[df["行业名称"].astype(str) == self.industry].copy()
        df["起始日期"] = pd.to_datetime(self._norm_dates(df["起始日期"]))
        df["结束日期"] = pd.to_datetime(self._norm_dates(df["结束日期"]))
        df = df.sort_values("起始日期").reset_index(drop=True)
        return df

    def _load_prices(self):
        df = pd.read_csv(self.index_csv_path)
        df["date"] = pd.to_datetime(df["date"])
        for c in ["open", "close", "high", "low", "volume", "amount"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        return df

    # ---------- 1b. 每日阶段标注 ----------
    def assign_phase(self):
        """给每个交易日标注 周期阶段_标准化 与 deviation_type"""
        px = self.prices.copy()
        dates = px["date"].values
        phase_arr = np.full(len(px), "未定义", dtype=object)
        dev_arr = np.full(len(px), "", dtype=object)
        seg_id_arr = np.full(len(px), -1, dtype=int)

        cycles = self.cycles.reset_index(drop=True)
        for i, row in cycles.iterrows():
            s, e = row["起始日期"], row["结束日期"]
            mask = (px["date"] >= s) & (px["date"] <= e)
            idx = np.where(mask.values)[0]
            if len(idx) == 0:
                continue
            phase_arr[idx] = row["周期阶段_标准化"]
            dev = row.get("deviation_type")
            if pd.notna(dev):
                dev_arr[idx] = str(dev)
            seg_id_arr[idx] = i

        px["phase"] = phase_arr
        px["deviation_type"] = dev_arr
        px["seg_id"] = seg_id_arr
        self.labeled = px
        return px

    # ---------- 1c/1d. 信号生成 + 净值 ----------
    def run_backtest(self, mode="binary"):
        """返回 (labeled_df, strategy_nav, benchmark_nav)。结果写回 self.labeled。"""
        if self.labeled is None:
            self.assign_phase()
        px = self.labeled
        rules = POSITION_RULES[mode]
        px["position"] = px["phase"].map(rules).fillna(0.0)

        # 日收益率（用 close）
        px["ret"] = px["close"].pct_change().fillna(0.0)
        # 策略日收益 = 仓位 × 标的日收益（空仓=现金，收益0）
        px["strategy_ret"] = px["position"] * px["ret"]
        px["benchmark_ret"] = px["ret"]

        px["strategy_nav"] = (1 + px["strategy_ret"]).cumprod()
        px["benchmark_nav"] = (1 + px["benchmark_ret"]).cumprod()
        self.labeled = px
        return px, px["strategy_nav"], px["benchmark_nav"]

    # ---------- 1e. 绩效计算 ----------
    @staticmethod
    def _nav_metrics(nav_series, ret_series):
        nav = nav_series.dropna()
        if len(nav) < 2:
            return dict(total_return=0, annual_return=0, max_drawdown=0,
                        sharpe=0, calmar=0)
        total_return = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
        n = len(nav)
        annual_return = ((nav.iloc[-1] / nav.iloc[0]) ** (TRADING_DAYS / n) - 1) * 100
        roll_max = nav.cummax()
        drawdown = (nav / roll_max - 1) * 100
        max_drawdown = drawdown.min()
        excess_ret = ret_series - RF_ANNUAL / TRADING_DAYS
        std = ret_series.std()
        sharpe = (excess_ret.mean() / std * np.sqrt(TRADING_DAYS)) if std > 0 else 0
        calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else np.inf
        return dict(total_return=total_return, annual_return=annual_return,
                    max_drawdown=max_drawdown, sharpe=sharpe, calmar=calmar)

    def calc_metrics(self, strategy_nav, benchmark_nav):
        labeled = self.labeled
        s_m = self._nav_metrics(strategy_nav, labeled["strategy_ret"])
        b_m = self._nav_metrics(benchmark_nav, labeled["benchmark_ret"])
        metrics = {
            "total_return": s_m["total_return"],
            "annual_return": s_m["annual_return"],
            "max_drawdown": s_m["max_drawdown"],
            "sharpe_ratio": s_m["sharpe"],
            "benchmark_annual": b_m["annual_return"],
            "benchmark_max_drawdown": b_m["max_drawdown"],
            "excess_annual_return": s_m["annual_return"] - b_m["annual_return"],
            "excess_max_drawdown": b_m["max_drawdown"] - s_m["max_drawdown"],
            "calmar_ratio": s_m["calmar"],
        }
        # 按周期段胜率
        phase_returns = self.phase_segment_returns(labeled)
        wins = sum(1 for r in phase_returns if r["strategy_ret"] > r["benchmark_ret"])
        metrics["win_rate_by_phase"] = wins / len(phase_returns) * 100 if phase_returns else 0
        metrics["phase_returns"] = phase_returns
        return metrics

    # ---------- 1f. 周期段拆解 ----------
    def build_segments(self):
        """构建周期段表：含数据覆盖与无数据覆盖两类"""
        if self.labeled is None:
            self.assign_phase()
        px = self.labeled
        data_start, data_end = px["date"].min(), px["date"].max()
        segs = []
        for i, row in self.cycles.reset_index(drop=True).iterrows():
            s, e = row["起始日期"], row["结束日期"]
            phase = row["周期阶段_标准化"]
            dev = row.get("deviation_type")
            dev = "" if pd.isna(dev) else str(dev)
            # 与日线区间求交
            ov_s = max(s, data_start); ov_e = min(e, data_end)
            if ov_s > ov_e:
                cover = "无数据覆盖"
                days = 0
            else:
                sub = px[(px["date"] >= ov_s) & (px["date"] <= ov_e)]
                days = len(sub)
                if days == 0:
                    cover = "无数据覆盖"
                elif s < data_start:
                    cover = "部分覆盖(左截断)"
                elif e > data_end:
                    cover = "部分覆盖(右截断)"
                else:
                    cover = "完整覆盖"
            segs.append(dict(seg_id=i, start=s, end=e, phase=phase,
                             deviation_type=dev, trading_days=days,
                             cover=cover, data_start=data_start, data_end=data_end))
        self.phase_segments = pd.DataFrame(segs)
        return self.phase_segments

    def phase_segment_returns(self, labeled=None):
        """每个有数据周期段的策略收益 vs 基准收益"""
        if self.phase_segments is None:
            self.build_segments()
        labeled = labeled if labeled is not None else self.labeled
        out = []
        for _, seg in self.phase_segments.iterrows():
            if seg["trading_days"] == 0:
                continue
            sub = labeled[(labeled["date"] >= seg["start"]) &
                          (labeled["date"] <= seg["end"])]
            if len(sub) < 2:
                continue
            s_nav = (1 + sub["strategy_ret"]).prod() - 1
            b_nav = (1 + sub["benchmark_ret"]).prod() - 1
            out.append(dict(seg_id=seg["seg_id"], start=str(seg["start"].date()),
                            end=str(seg["end"].date()), phase=seg["phase"],
                            deviation_type=seg["deviation_type"],
                            days=seg["trading_days"],
                            strategy_ret=s_nav * 100, benchmark_ret=b_nav * 100,
                            excess=(s_nav - b_nav) * 100))
        return out

    # ---------- 单行业报告 ----------
    def generate_report(self, mode="binary"):
        labeled, s_nav, b_nav = self.run_backtest(mode)
        m = self.calc_metrics(s_nav, b_nav)
        segs = self.build_segments()
        return {"industry": self.industry, "mode": mode, "metrics": m,
                "segments": segs, "labeled": labeled,
                "strategy_nav": s_nav, "benchmark_nav": b_nav,
                "data_start": str(labeled["date"].min().date()),
                "data_end": str(labeled["date"].max().date()),
                "n_trading_days": len(labeled)}


if __name__ == "__main__":
    # 自测：煤炭
    bt = CycleTimingBacktest("煤炭")
    rep = bt.generate_report("binary")
    m = rep["metrics"]
    print(f"=== {rep['industry']} binary模式 ===")
    print(f"区间: {rep['data_start']} ~ {rep['data_end']}  交易日:{rep['n_trading_days']}")
    print(f"策略年化: {m['annual_return']:.2f}%  基准年化: {m['benchmark_annual']:.2f}%  "
          f"超额: {m['excess_annual_return']:+.2f}%")
    print(f"夏普: {m['sharpe_ratio']:.2f}  策略回撤: {m['max_drawdown']:.2f}%  "
          f"基准回撤: {m['benchmark_max_drawdown']:.2f}%  胜率: {m['win_rate_by_phase']:.0f}%")
    print("\n周期段拆解:")
    print(rep["segments"][["seg_id", "phase", "trading_days", "cover",
                           "deviation_type"]].to_string(index=False))
