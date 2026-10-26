#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产能周期投资系统 v1.0 — 统一命令行入口
================================================
用法：
  python3 main.py dashboard           # 终端仪表盘（默认命令）
  python3 main.py dashboard --html    # 生成HTML仪表盘并用浏览器打开
  python3 main.py update              # 增量更新全部数据 + 预警
  python3 main.py alert               # 运行预警检查
  python3 main.py backtest            # 重新运行全量回测（耗时较长）
  python3 main.py report <行业名>     # 生成单行业四维报告
  python3 main.py status              # 简要状态（数据日期 + 预警计数）
  python3 main.py replay <时间窗口>   # 市场复盘(2025Q1/2025H1/2025/202502/20250205-20250307/recent30/recent90/ytd)
  python3 main.py overview            # 31行业全季度总览(2015至今)
  python3 main.py switch              # 主线切换分析(连续TOP3主线+切换事件)
  python3 main.py compare [行业]      # 同类主线切换横向对比
  python3 main.py heatmap             # 季度热力图+切换快照+产能周期叠加分析
  python3 main.py mainline [年份]     # 年度主线演变全景报告(默认2025)
  python3 main.py decade [起] [止]    # 十年主线迁移全景报告(默认2015-2025)
  python3 main.py switch-study [起] [止]  # 主线切换深度研究(默认2016-2025)
  python3 main.py help                # 显示帮助
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "dashboard"))
sys.path.insert(0, os.path.join(BASE_DIR, "backtest"))
sys.path.insert(0, os.path.join(BASE_DIR, "data_feeds"))


def cmd_dashboard(html=False):
    """显示22行业仪表盘"""
    from dashboard.cycle_dashboard import CycleDashboard
    db = CycleDashboard(BASE_DIR)
    db.load_all()
    if html:
        output_path = db.generate_html()
        print(f"HTML仪表盘已生成: {output_path} ({os.path.getsize(output_path)//1024} KB)")
        try:
            os.system(f"open '{output_path}'")  # macOS打开浏览器
        except Exception:
            pass
    else:
        db.print_terminal()


def cmd_update():
    """增量更新全部数据，更新完自动运行预警"""
    from data_feeds.incremental_update import IncrementalUpdater
    updater = IncrementalUpdater()
    updater.update_all()
    print("\n--- 数据更新完成，运行预警检查 ---")
    cmd_alert()


def cmd_alert():
    """运行预警检查"""
    from dashboard.alert_engine import AlertEngine
    engine = AlertEngine()
    results = engine.run_full_check()
    report = engine.generate_alert_report(results)
    # 复用引擎的终端打印
    import dashboard.alert_engine as ae
    ae._print_report(results, report)
    path = engine.append_alerts_log(results)
    print(f"\n预警日志已追加: {path}")
    return results


def cmd_backtest():
    """重新运行全量回测"""
    print("开始全量回测(22行业 x 3模式)，耗时约10秒...")
    import backtest.backtest_engine as be
    summary_df, phase_df, reports = be.run_all()
    be.phase_effectiveness(phase_df)
    be.deviation_analysis(phase_df)
    print(f"\n回测完成: {len(summary_df)}行业。生成图表...")
    # 重新生成图表
    try:
        import backtest.make_charts as mc
        mc.main()
    except Exception as e:
        print(f"图表生成跳过: {e}")
    print(f"结果: backtest/backtest_results/")


def cmd_report(industry_name):
    """生成单行业四维报告(integrated_analyzer.py)"""
    import subprocess
    # integrated_analyzer.py 位于父目录(项目原位置)
    candidates = [
        os.path.join(BASE_DIR, "integrated_analyzer.py"),
        os.path.join(os.path.dirname(BASE_DIR), "integrated_analyzer.py"),
    ]
    analyzer = next((c for c in candidates if os.path.exists(c)), None)
    if analyzer is None:
        print("✗ 找不到 integrated_analyzer.py")
        return
    work_dir = os.path.dirname(analyzer)
    print(f"运行: {analyzer} {industry_name} (工作目录 {work_dir})")
    r = subprocess.run([sys.executable, analyzer, industry_name],
                       capture_output=True, text=True, cwd=work_dir)
    out = r.stdout or ""
    # 过滤 akshare 广告/警告噪音
    lines = [ln for ln in out.splitlines()
             if "大V" not in ln and "的广告" not in ln
             and "FutureWarning" not in ln and "to_pydatetime" not in ln
             and ln.strip() not in (":",)]
    print("\n".join(lines))
    if r.returncode != 0 and r.stderr:
        print("[stderr]", r.stderr[-300:])


def cmd_status():
    """简要状态：数据最新日期 + 预警计数 + CSV记录数"""
    import pandas as pd
    from datetime import datetime
    print("=" * 56)
    print("  产能周期投资系统 — 状态")
    print("=" * 56)
    # 指数最新日期
    idx_dir = os.path.join(BASE_DIR, "raw_data", "index_daily")
    dates = []
    n_idx = 0
    for f in os.listdir(idx_dir):
        if f.endswith(".csv"):
            n_idx += 1
            try:
                d = pd.read_csv(os.path.join(idx_dir, f), usecols=[0])
                dates.append(str(d.iloc[-1, 0]))
            except Exception:
                pass
    print(f"  行业指数日线: {n_idx}个CSV, 最新 {max(dates) if dates else '?'}")
    # 指标
    ind_dir = os.path.join(BASE_DIR, "raw_data", "indicators")
    for f in sorted(os.listdir(ind_dir)):
        if f.endswith(".csv"):
            try:
                d = pd.read_csv(os.path.join(ind_dir, f))
                # 估值快照表用 snapshot_date 列，否则用首列日期
                if "snapshot_date" in d.columns:
                    last = str(d["snapshot_date"].iloc[-1])
                else:
                    last = str(d.iloc[-1, 0])
                print(f"  指标 {f:<34} 最新 {last} ({len(d)}行)")
            except Exception:
                pass
    # 预警计数
    alerts_csv = os.path.join(BASE_DIR, "raw_data", "alerts", "alerts_log.csv")
    if os.path.exists(alerts_csv):
        al = pd.read_csv(alerts_csv)
        today = datetime.now().strftime("%Y-%m-%d")
        today_n = (al["日期"].astype(str) == today).sum()
        red = (al["预警级别"] == "转换").sum()
        print(f"  预警日志: 共{len(al)}条 | 今日{today_n}条 | 累计转换预警{red}条")
    # 回测时间
    bt_csv = os.path.join(BASE_DIR, "backtest", "backtest_results", "cycle_timing_summary.csv")
    if os.path.exists(bt_csv):
        import time as _t
        mt = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(os.path.getmtime(bt_csv)))
        n = len(pd.read_csv(bt_csv))
        print(f"  回测汇总: {n}行业, 上次更新 {mt}")
    # 周期CSV
    cyc = pd.read_csv(os.path.join(BASE_DIR, "raw_data", "industry_cycle.csv"))
    print(f"  周期标注: {len(cyc)}条记录, {cyc['行业名称'].nunique()}个行业")


def cmd_help():
    print(__doc__)


def cmd_chronicle(start=2016, end=2025):
    """主线编年史报告(逐年逐段叙事 + 跨年纵向分析)"""
    from dashboard.mainline_chronicle_report import generate_chronicle_report
    generate_chronicle_report(start, end)


def cmd_narrative(year=2023):
    """年度深度叙事报告(券商研报式主线复盘)"""
    from dashboard.annual_deep_narrative import generate_deep_narrative
    generate_deep_narrative(year)


def _make_full_replay():
    """构造覆盖2015~今天的MarketReplay实例(用于全周期分析)"""
    from dashboard.market_replay import MarketReplay
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    replay = MarketReplay(BASE_DIR, "2015-01-01", today, label="全周期")
    replay.load_data()
    replay.load_sw31_data()
    replay.load_full_catalysts()
    return replay


def cmd_replay_overview():
    """生成46季度全行业总览"""
    replay = _make_full_replay()
    replay.save_quarterly_overview()


def cmd_replay_switch():
    """生成主线切换分析"""
    replay = _make_full_replay()
    replay.save_mainline_analysis()


def cmd_replay_compare(industry=None):
    """同类切换横向对比"""
    replay = _make_full_replay()
    stats, summary = replay.cross_period_comparison(industry)
    print(summary)
    if stats is not None and hasattr(stats, "to_csv"):
        path = os.path.join(BASE_DIR, "raw_data", "mainline_compare.csv")
        stats.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"✅ 对比结果: {path}")


def cmd_heatmap():
    """生成热力图+切换快照+产能周期叠加"""
    from dashboard.heatmap_generator import HeatmapGenerator
    gen = HeatmapGenerator()
    if not gen.load_data():
        return
    print("\n[1/3] 季度热力图...")
    path = gen.generate_quarterly_heatmap_html()
    print("\n[2/3] 主线切换快照...")
    snapshots, summary = gen.generate_switch_snapshots()
    print(summary)
    print("\n[3/3] 产能周期×主线分析...")
    gen.generate_cycle_mainline_analysis()
    print(f"\n热力图: dashboard/replay_reports/quarterly_heatmap.html")
    print(f"切换快照: dashboard/replay_reports/switch_snapshots.html")


def cmd_mainline_report(year=2025):
    """生成年度主线演变全景报告"""
    from dashboard.annual_mainline_report import generate_annual_mainline_report
    generate_annual_mainline_report(year)


def cmd_decade_report(start_year=2015, end_year=2025):
    """生成十年主线迁移全景报告"""
    from dashboard.decade_mainline_report import generate_decade_report
    generate_decade_report(start_year, end_year)


def cmd_switch_study(start_year=2016, end_year=2025):
    """主线切换深度研究"""
    from dashboard.switch_study_report import generate_switch_study_report
    generate_switch_study_report(start_year, end_year)


def cmd_replay(window_str):
    """市场复盘: python3 main.py replay <时间窗口>"""
    from dashboard.market_replay import MarketReplay, parse_time_window
    try:
        start, end = parse_time_window(window_str)
    except Exception as e:
        print(f"✗ {e}")
        print("支持格式: 2025Q1 / 2025H1 / 2025 / 202502 / 20250205-20250307 / recent30 / recent90 / ytd")
        return
    print(f"复盘窗口: {start} ~ {end}")
    replay = MarketReplay(BASE_DIR, start, end, label=window_str)
    replay.load_data()
    replay.print_terminal()
    html_path = replay.generate_html()
    print(f"\n完整报告: {html_path} ({os.path.getsize(html_path)//1024} KB)")
    try:
        os.system(f"open '{html_path}'")  # macOS打开浏览器
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        cmd_dashboard()
        return
    command = sys.argv[1].lower()
    if command == "dashboard":
        cmd_dashboard(html=("--html" in sys.argv))
    elif command == "update":
        cmd_update()
    elif command == "alert":
        cmd_alert()
    elif command == "backtest":
        cmd_backtest()
    elif command == "report":
        if len(sys.argv) < 3:
            print("用法: python3 main.py report <行业名>  (例: python3 main.py report 煤炭)")
            return
        cmd_report(sys.argv[2])
    elif command == "status":
        cmd_status()
    elif command == "replay":
        if len(sys.argv) < 3:
            print("用法: python3 main.py replay <时间窗口|mainline [年份]>")
            print("  2025Q1/2025H1/2025/202502/20250205-20250307/recent30/recent90/ytd")
            print("  mainline [年份]  年度主线演变全景报告")
            return
        if sys.argv[2] == "mainline":
            year = 2025
            if len(sys.argv) > 3:
                try:
                    year = int(sys.argv[3])
                except ValueError:
                    pass
            cmd_mainline_report(year)
        elif sys.argv[2] == "decade":
            start_y, end_y = 2015, 2025
            if len(sys.argv) > 3:
                try:
                    start_y = int(sys.argv[3])
                except ValueError:
                    pass
            if len(sys.argv) > 4:
                try:
                    end_y = int(sys.argv[4])
                except ValueError:
                    pass
            cmd_decade_report(start_y, end_y)
        else:
            cmd_replay(sys.argv[2])
    elif command == "overview":
        cmd_replay_overview()
    elif command == "switch":
        cmd_replay_switch()
    elif command == "compare":
        cmd_replay_compare(sys.argv[2] if len(sys.argv) > 2 else None)
    elif command == "heatmap":
        cmd_heatmap()
    elif command == "mainline":
        year = 2025
        if len(sys.argv) > 2:
            try:
                year = int(sys.argv[2])
            except ValueError:
                pass
        cmd_mainline_report(year)
    elif command == "decade":
        start_y, end_y = 2015, 2025
        if len(sys.argv) > 2:
            try:
                start_y = int(sys.argv[2])
            except ValueError:
                pass
        if len(sys.argv) > 3:
            try:
                end_y = int(sys.argv[3])
            except ValueError:
                pass
        cmd_decade_report(start_y, end_y)
    elif command == "switch-study":
        start_y, end_y = 2016, 2025
        if len(sys.argv) > 2:
            try:
                start_y = int(sys.argv[2])
            except ValueError:
                pass
        if len(sys.argv) > 3:
            try:
                end_y = int(sys.argv[3])
            except ValueError:
                pass
        cmd_switch_study(start_y, end_y)
    elif command == "chronicle":
        start_y, end_y = 2016, 2025
        if len(sys.argv) > 2:
            try:
                start_y = int(sys.argv[2])
            except ValueError:
                pass
        if len(sys.argv) > 3:
            try:
                end_y = int(sys.argv[3])
            except ValueError:
                pass
        cmd_chronicle(start_y, end_y)
    elif command == "narrative":
        year = 2023
        if len(sys.argv) > 2:
            try:
                year = int(sys.argv[2])
            except ValueError:
                pass
        cmd_narrative(year)
    elif command in ("help", "-h", "--help"):
        cmd_help()
    else:
        print(f"未知命令: {command}")
        cmd_help()


if __name__ == "__main__":
    main()
