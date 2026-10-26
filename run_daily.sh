#!/bin/bash
# 每日数据更新 + 预警检查 (阶段3)
# 用法: 手动执行 bash run_daily.sh，或由 crontab/launchd 在交易日17:00调用
cd "$(dirname "$0")"

echo "$(date '+%Y-%m-%d %H:%M:%S') === 每日数据更新开始 ==="

# 2026-10-03修复: 10-01那次 incremental_update.py 因无超时的网络调用挂死31小时,
# launchd 同标签在旧实例存活时不再触发新实例,把10-02的每日任务堵没了。
# 看门狗: 全流程超45分钟则强杀自身,释放launchd保证次日正常触发
( sleep 2700; echo "$(date '+%Y-%m-%d %H:%M:%S') [看门狗] 超时45分钟,强制终止"; pkill -TERM -P $$ 2>/dev/null; kill -TERM $$ ) &
WATCHDOG=$!

# 清除代理(本环境代理7890返回502，强制直连)
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export NO_PROXY=*

# 1. 增量更新22行业指数 + 6类核心指标
python3 data_feeds/incremental_update.py 2>&1

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') --- 预警检查 ---"

# 2. 运行预警引擎(转换触发 + 领先信号见底)，追加 alerts_log.csv
python3 dashboard/alert_engine.py 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') === 每日更新完成 ==="

kill $WATCHDOG 2>/dev/null
