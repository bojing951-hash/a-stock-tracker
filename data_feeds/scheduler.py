# -*- coding: utf-8 -*-
"""
定时调度说明 (阶段3)
================================================
设计决策: 不使用 APScheduler 常驻进程(在 macOS 后台运行不稳定、易被系统挂起)。
改为用 macOS 原生 crontab 或 launchd 调度 run_daily.sh / run_weekly.sh。
本文件仅作为调度配置说明 + (可选)提供一次性立即执行入口。

调度计划
--------
每日  17:00 (交易日收盘后, 周一~周五):
    run_daily.sh
      -> data_feeds/incremental_update.py   增量更新22行业指数 + 6类指标
      -> dashboard/alert_engine.py          预警检查(转换/领先信号)
      -> 追加 raw_data/alerts/alerts_log.csv

每周五 17:30 (收盘后):
    run_weekly.sh
      -> run_daily.sh
      -> integrated_analyzer.py (22行业四维报告重生成)
      -> dashboard/cycle_dashboard.py (阶段4仪表盘)

设置方法 (任选其一)
-------------------
【方法1: crontab】
    crontab -e
    加入:
    0 17 * * 1-5 /path/to/a-stock-tracker/run_daily.sh >> /path/to/a-stock-tracker/daily.log 2>&1
    30 17 * * 5 /path/to/a-stock-tracker/run_weekly.sh >> /path/to/a-stock-tracker/weekly.log 2>&1

【方法2: launchd】(推荐, macOS 原生, 支持睡眠唤醒后补跑)
    复制 com.a_stock.daily.plist / com.a_stock.weekly.plist 到 ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.a_stock.daily.plist
    (模板见文末 LAUNCHD_DAILY / LAUNCHD_WEEKLY)

注意
----
- crontab/launchd 环境变量干净, 无 PATH 问题; run_daily.sh 内会 cd 到项目目录并清代理。
- 17:00 收盘后跑, 数据源当日数据通常 16:30 后才更新完整。
- 非交易日(周末/节假日)运行无害: 增量更新会显示"已是最新"。
"""
import os
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DAILY = os.path.join(BASE_DIR, "run_daily.sh")
RUN_WEEKLY = os.path.join(BASE_DIR, "run_weekly.sh")

LAUNCHD_DAILY = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.a_stock.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>__BASE__/run_daily.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer>
        <key>Weekday</key><array><integer>1</integer><integer>2</integer><integer>3</integer><integer>4</integer><integer>5</integer></array></dict>
  <key>StandardOutPath</key><string>__BASE__/daily.log</string>
  <key>StandardErrorPath</key><string>__BASE__/daily.log</string>
</dict></plist>
""".replace("__BASE__", BASE_DIR)


def run_now_daily():
    """立即执行一次每日流程(用于测试/手动触发)"""
    return subprocess.run(["/bin/bash", RUN_DAILY], capture_output=False)


if __name__ == "__main__":
    print(__doc__)
    print("\n--- launchd daily 模板 ---\n")
    print(LAUNCHD_DAILY)
