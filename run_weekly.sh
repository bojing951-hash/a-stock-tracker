#!/bin/bash
# 每周报告重生成 (阶段3)
# 用法: 手动执行 bash run_weekly.sh，或由 crontab/launchd 在每周五17:30调用
cd "$(dirname "$0")"

# 1. 先跑每日流程(数据更新 + 预警)
bash run_daily.sh

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === 每周报告生成开始 ==="

# 清除代理
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export NO_PROXY=*

# 2. 对所有22行业重新生成四维报告(integrated_analyzer.py 逐行业)
# 2026-09-30修复: ① analyzer已上移到项目根目录(原相对路径因文件移动导致每周静默跳过)
#                ② 显式用 /usr/bin/python3(该环境有plotly;交互shell的python3缺plotly会全部失败)
PY=/usr/bin/python3
$PY -c "
import subprocess, sys, os
import pandas as pd
cycle = pd.read_csv('raw_data/industry_cycle.csv')
industries = sorted(cycle['行业名称'].astype(str).unique())
analyzer = os.path.join(os.path.dirname(os.getcwd()), 'integrated_analyzer.py')  # 可选外部工具,缺省自动跳过
if not os.path.exists(analyzer):
    print(f'[跳过] {analyzer} 不存在，无法重生成四维报告')
    sys.exit(0)
ok = 0
for ind in industries:
    r = subprocess.run([sys.executable, analyzer, ind], capture_output=True, text=True)
    if r.returncode == 0:
        ok += 1
    else:
        print(f'  [失败] {ind}: {r.stderr[:120]}')
print(f'四维报告重生成完成: {ok}/{len(industries)}')
" 2>&1

# 3. 仪表盘(阶段4, 若存在)
if [ -f dashboard/cycle_dashboard.py ]; then
  echo "--- 刷新综合仪表盘 ---"
  $PY dashboard/cycle_dashboard.py 2>&1 || echo "[警告] 仪表盘生成失败(阶段4未完成时正常)"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') === 每周报告完成 ==="
