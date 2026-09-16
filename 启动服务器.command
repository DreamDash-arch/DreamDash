#!/bin/bash
# 双击本文件即可启动 DreamDash 局域网联机主机
cd "$(dirname "$0")" || exit 1
clear

if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3。"
  echo "请先安装 Python 3：https://www.python.org/downloads/"
  echo
  read -n 1 -s -r -p "按任意键关闭窗口…"
  exit 1
fi

echo "============================================================"
echo "  DreamDash 局域网联机主机"
echo "============================================================"
echo "  启动后，把终端里「局域网访问」那个地址发给朋友即可。"
echo "  这个窗口要一直开着，关掉就等于关服。"
echo "  想停止：在这个窗口按 Control + C"
echo "============================================================"
echo

python3 server.py "$@"
STATUS=$?

echo
if [ $STATUS -ne 0 ]; then
  echo "启动失败（可能是 8000 端口被占用）。"
  echo "可以试试换端口：在「终端」里执行  python3 server.py --port 9000"
fi
read -n 1 -s -r -p "按任意键关闭窗口…"
