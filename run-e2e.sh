#!/usr/bin/env bash
# 跑手机 E2E。**用自己的端口和自己的库**，不碰 8000 上那个服务、不碰 data/nagaya.db。
#
# 原来这个脚本是 `kill -9` 掉 8000 端口上的进程、`rm` 掉 data/nagaya.db 再 seed ——
# 开发机和自用的那台是同一台、同一个仓库时，跑一次 E2E 就把真账本删了。
#
# 每次都把 E2E 专用库重置到确定基线再跑：E2E 是真往库里写的，而断言一失败就跳过收尾，
# 残渣会让下一轮别的用例红在一个跟它毫无关系的地方（真发生过：离线草稿那条读到了
# 另一条用例留下的 903，查了半天）。用例里的 afterEach 只管同一轮内的卫生；跨轮的确定性靠这里。
#
#   ./run-e2e.sh                 # 全跑
#   ./run-e2e.sh -g 固定费        # 参数原样交给 playwright
#   E2E_PORT=8799 ./run-e2e.sh   # 换端口
set -e
cd "$(dirname "$0")"
ROOT=$(pwd)
PORT=${E2E_PORT:-8765}
DB="$ROOT/backend/data/e2e.db"
export NAGAYA_URL="http://127.0.0.1:$PORT"

stop_test_server() {
  lsof -ti "tcp:$PORT" | xargs kill 2>/dev/null || true
}

echo "→ 重置 E2E 专用库：$DB"
stop_test_server
cd "$ROOT/backend"
rm -f "$DB" "$DB-wal" "$DB-shm"
NAGAYA_DB="$DB" .venv/bin/python -m tools.seed_dev > /dev/null

# 先打包再起服务：后端开机时认一次 dist 目录在不在
echo "→ 打包前端"
cd "$ROOT/frontend"
npm run build --silent

echo "→ 起测试服务：$NAGAYA_URL"
cd "$ROOT/backend"
NAGAYA_DB="$DB" nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  > /tmp/nagaya-e2e.log 2>&1 &
for _ in $(seq 1 20); do
  curl -sf "$NAGAYA_URL/api/health" > /dev/null && break
  sleep 0.5
done

# 用 trap 而不是写在末尾：set -e 下用例一红脚本就退了，收尾得照样跑
cleanup() {
  echo "→ 收尾：停掉测试服务、删掉 E2E 专用库"
  stop_test_server
  rm -f "$DB" "$DB-wal" "$DB-shm"
}
trap cleanup EXIT

echo "→ 跑 E2E"
cd "$ROOT/frontend"
npx playwright test "$@"
