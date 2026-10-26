#!/bin/bash
# 产能周期系统 - 定时任务管理
# 用法: bash manage_schedule.sh {start|stop|status|test|log}

DAILY=~/Library/LaunchAgents/com.astock.daily.plist
WEEKLY=~/Library/LaunchAgents/com.astock.weekly.plist
LOG_DIR="$(cd "$(dirname "$0")" && pwd)/logs"

case "$1" in
    start)
        launchctl load "$DAILY" 2>/dev/null
        launchctl load "$WEEKLY" 2>/dev/null
        echo "定时任务已启动"
        launchctl list | grep astock
        ;;
    stop)
        launchctl unload "$DAILY" 2>/dev/null
        launchctl unload "$WEEKLY" 2>/dev/null
        echo "定时任务已停止"
        ;;
    status)
        echo "=== 定时任务状态 ==="
        launchctl list | grep astock || echo "(未加载)"
        echo ""
        echo "=== 最近日志 daily.log (最后5行) ==="
        tail -5 "$LOG_DIR/daily.log" 2>/dev/null || echo "无日志"
        echo ""
        echo "=== 最近错误 daily_error.log (最后5行) ==="
        tail -5 "$LOG_DIR/daily_error.log" 2>/dev/null || echo "无错误"
        ;;
    test)
        echo "手动触发每日任务..."
        : > "$LOG_DIR/daily.log"; : > "$LOG_DIR/daily_error.log"
        before=$(wc -l < "$(dirname "$0")/raw_data/alerts/alerts_log.csv" 2>/dev/null || echo 0)
        launchctl start com.astock.daily
        # 轮询等待完成(最多120秒)
        for i in $(seq 1 40); do
            sleep 3
            if grep -q "每日更新完成" "$LOG_DIR/daily.log" 2>/dev/null; then
                echo "[完成] 约$((i*3))秒"
                break
            fi
        done
        after=$(wc -l < "$(dirname "$0")/raw_data/alerts/alerts_log.csv" 2>/dev/null || echo 0)
        echo "=== 运行结果 daily.log (最后20行) ==="
        tail -20 "$LOG_DIR/daily.log"
        echo ""
        echo "alerts_log.csv: ${before}行 -> ${after}行"
        echo "daily_error.log: $([ -s "$LOG_DIR/daily_error.log" ] && echo '有错误' || echo '无错误')"
        ;;
    log)
        cat "$LOG_DIR/daily.log" 2>/dev/null || echo "无日志"
        ;;
    weeklytest)
        echo "手动触发每周任务(耗时较长,生成22行业报告)..."
        launchctl start com.astock.weekly
        echo "已触发,查看 weekly.log: tail -f $LOG_DIR/weekly.log"
        ;;
    *)
        echo "用法: bash manage_schedule.sh {start|stop|status|test|log|weeklytest}"
        ;;
esac
