#!/usr/bin/env bash
# 本地起后端。换端口：PORT=9001 ./run.sh
set -e
cd "$(dirname "$0")"
# 新建的文件只给自己读写：账本、-wal、日志、.secret 都是整本账或能签 token 的东西，
# 和备份（0600/0700）一个待遇。已经存在的文件不受影响，要收紧就手动 chmod 一次
umask 077
# Linux 上 glibc 给每个线程开一块自己的堆（最多「核数 × 8」块），线程池里几十个线程
# 各占一块、用完不还，常驻内存就这么一点点涨上去。两块足够这点并发。macOS 上没有这回事
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
