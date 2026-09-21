#!/usr/bin/env bash
# 跑手机 E2E。**每次都把开发库重置到确定基线**再跑。
#
# 为什么非这样不可：E2E 是真往库里写的，而断言一失败就跳过收尾，残渣留在
# 共享的开发库里。下一轮别的用例读到它，然后红在一个跟它毫无关系的地方
# （真发生过：离线草稿那条读到了另一条用例留下的 903，查了半天）。
# 用例里的 afterEach 只管同一轮内的卫生；跨轮的确定性靠这里。
set -e
cd "$(dirname "$0")"
ROOT=$(pwd)

echo "→ 停服务"
lsof -ti tcp:8000 | xargs kill -9 2>/dev/null || true

echo "→ 重置开发库"
cd backend
rm -f data/nagaya.db data/nagaya.db-wal data/nagaya.db-shm
.venv/bin/python -m tools.seed_dev

echo "→ 起服务"
nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/nagaya-uvicorn.log 2>&1 &
for _ in $(seq 1 20); do
  curl -sf http://127.0.0.1:8000/api/health > /dev/null && break
  sleep 0.5
done

echo "→ 打包前端"
cd ../frontend
npm run build --silent

# ---------------------------------------------------------------- 收尾
# 用例把库写脏了，而且测试服务只监听 127.0.0.1（手机连不上）。
# 用 trap 而不是写在末尾：set -e 下用例一红脚本就退了，收尾得照样跑。
restore() {
  echo "→ 收尾：重置开发库，换回对内网开放的服务"
  lsof -ti tcp:8000 | xargs kill -9 2>/dev/null || true
  cd "$ROOT/backend"
  rm -f data/nagaya.db data/nagaya.db-wal data/nagaya.db-shm
  .venv/bin/python -m tools.seed_dev > /dev/null
  nohup ./run.sh > /tmp/nagaya-uvicorn.log 2>&1 &
  for _ in $(seq 1 20); do
    curl -sf http://127.0.0.1:8000/api/health > /dev/null && break
    sleep 0.5
  done
  local ip
  ip=$(ipconfig getifaddr en0 2>/dev/null || echo localhost)
  echo "→ 已恢复：http://$ip:8000"
}
trap restore EXIT

echo "→ 跑 E2E"
npx playwright test "$@"
