#!/usr/bin/env bash
# 浏览器级巡检：临时拉起服务 → 真实登录 → 逐页检查 → 关服务。
# 用法：bash tools/browser_sweep.sh [port]
# 依赖：agent-browser（node 全局安装）。无 agent-browser 时脚本会直接退出，不影响项目本身。
set -u

PORT="${1:-8123}"
BASE="http://127.0.0.1:${PORT}"
PY="D:/Anaconda/Anaconda/python.exe"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/data/browser_sweep.log"

mkdir -p "$ROOT/data"

command -v agent-browser >/dev/null 2>&1 || { echo "跳过：未安装 agent-browser"; exit 0; }

cd "$ROOT"   # 必须：--app-dir 要用相对路径，Windows 版 Python 不认 /d/... 这种 MSYS 风格路径

echo "== 启动临时服务 :$PORT =="
"$PY" -u -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
SRV=$!
trap 'kill "$SRV" 2>/dev/null' EXIT

for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 2 "$BASE/login" || true)
  [ "$code" = "200" ] && break
  sleep 0.5
done
[ "$code" = "200" ] || { echo "服务未起来，见 $LOG"; exit 1; }

probe() {
  agent-browser eval "(() => { const t=document.body.innerText; \
    const bad=(t.match(/读取失败|加载失败|请求失败|undefined|NaN|\[object Object\]/g)||[]); \
    return location.pathname+' | len='+t.length+' cards='+document.querySelectorAll('.card').length \
      +' tabs='+document.querySelectorAll('.tab').length+' bad='+bad.length; })()" 2>&1 | tail -1
}

login_as() {
  agent-browser close --all >/dev/null 2>&1
  agent-browser open "$BASE/login" >/dev/null 2>&1
  agent-browser wait 2200 >/dev/null 2>&1
  agent-browser fill "#username" "$1" >/dev/null 2>&1
  agent-browser fill "#password" "123456" >/dev/null 2>&1
  agent-browser click "button[type=submit]" >/dev/null 2>&1
  agent-browser wait 3000 >/dev/null 2>&1
  echo "-- 登录 $1 → $(agent-browser eval "location.pathname" 2>&1 | tail -1)"
}

sweep() {
  for p in $1; do
    agent-browser open "$BASE$p" >/dev/null 2>&1
    agent-browser wait 2200 >/dev/null 2>&1
    echo "$p -> $(probe)"
  done
}

echo
echo "== 教师端 =="
login_as teacher
sweep "/teacher /teach /tutor /resources /grade /match /library /homework /profile"

echo
echo "== 学生端 =="
login_as stu01
sweep "/student /ask /hub /homework /match /library /profile"

agent-browser close --all >/dev/null 2>&1
echo
echo "== 巡检结束 =="
