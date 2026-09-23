#!/usr/bin/env bash
# 長屋 nagaya 一键部署。两种装法：
#
#   bash deploy.sh            直接装在 Linux 上（Debian / Ubuntu 的 LXC、虚拟机或裸机，root，systemd）
#   bash deploy.sh --docker   用 Docker 起（NAS、或者任何装了 Docker 的机器，Mac 也行）
#
# 直接装：装 uv（自带独立 Python）→ 装后端依赖 → 装 Node（系统里没有或太旧才装，放在项目的
#   .tools/ 里，不碰系统）→ 打包前端 → 生成 systemd 服务并启动 → 真去打一次接口确认活着。
# Docker：打镜像（Node 和 Python 都在镜像里）→ docker compose up。账本和备份挂在宿主机的
#   backend/data、backend/backups（和直接装是同一个位置），删容器不会删它们。
#
# 第一次部署（还没有账本、或者账本里一个人都没有）时中途会问几句：端口、要不要把旧机器的
# 账本搬过来、备份放哪（只有直接装才问）、第一个账号。问不了人（不是终端、或者
# NAGAYA_YES=1）时全用默认；`PORT=9001 bash deploy.sh` 预设端口。
#
# 幂等：任何一步失败立刻停下并说清楚，修完重跑就行，不会留半成品。
# 升级：`git pull && bash deploy.sh`（Docker 就加 --docker）—— 不问问题、不碰账本；
#   表结构变了开机自动升级（升之前在 backend/data/ 里留一份 before-migrate-*.db 快照）。
# 路径全部由脚本自身位置推导，仓库克隆到哪都行。
set -euo pipefail
# 这个脚本建出来的东西（账本目录、导入的账本、.env）只给自己读写 —— 和 run.sh 一个待遇
umask 077
# 用户是在哪个目录下敲的这条命令：问「备份文件路径」时，相对路径按这里算
ORIG_PWD="$PWD"

SVC=nagaya
PORT_DEFAULT=8000
PYVER=3.12
#: vite 8 / vitest 5 要 Node 22.12+ 或 24
NODE_MAJOR=24

say() { printf '%s\n' "$*"; }
die() { printf '❌ %s\n' "$*" >&2; exit 1; }
# 能不能问人：得是终端，而且没设 NAGAYA_YES
interactive() { [ -t 0 ] && [ -z "${NAGAYA_YES:-}" ]; }
# ask 变量名 "问题" [默认值] —— 问不了人时直接取默认
ask() {
  local __ans=''
  if interactive; then read -r -p "$2${3:+ [$3]}: " __ans || true; fi
  printf -v "$1" '%s' "${__ans:-${3:-}}"
}
# confirm "问题"（默认是） —— 问不了人时当「是」
confirm() {
  local a=''
  if interactive; then read -r -p "$1 [Y/n]: " a || true; fi
  case "$a" in [nN]*) return 1 ;; *) return 0 ;; esac
}
# 收尾：这一趟要是把服务停了又半路失败，替人把它起回来，并且说清楚
STOPPED=0
TMP=''
cleanup() {
  local rc=$?
  [ -n "$TMP" ] && rm -rf "$TMP"
  if [ "$rc" != 0 ] && [ "$STOPPED" = 1 ]; then
    if systemctl start "$SVC" 2>/dev/null; then
      printf '⚠ 部署半路失败了；服务是这一趟停掉的，已经按原样起回来了（跑的还是旧版）\n' >&2
    else
      printf '⚠ 部署半路失败了，而且服务现在是停着的：修好上面的问题再重跑，或者 systemctl start %s\n' "$SVC" >&2
    fi
  fi
}
trap cleanup EXIT
stop_service() {
  if systemctl is-active --quiet "$SVC" 2>/dev/null; then
    systemctl stop "$SVC"
    STOPPED=1
  fi
}

check_port() {
  case "$PORT" in ''|*[!0-9]*) die "端口必须是数字：$PORT" ;; esac
  [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "端口超范围（1-65535）：$PORT"
}
local_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
  command -v ipconfig >/dev/null && ipconfig getifaddr en0 2>/dev/null || true
}

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$APP/backend"
FRONTEND="$APP/frontend"
DB="$BACKEND/data/nagaya.db"
[ -f "$BACKEND/app/main.py" ]        || die "$BACKEND 下没有 app/main.py —— deploy.sh 必须放在 nagaya 项目根目录"
[ -f "$FRONTEND/package-lock.json" ] || die "$FRONTEND 下没有 package-lock.json"
[ -f "$BACKEND/requirements.lock" ]  || die "$BACKEND 下没有 requirements.lock"
case "$APP" in *[[:space:]]*) die "项目路径含空格（systemd / compose 都不好处理）：$APP" ;; esac

# 在后端的 Python 里跑一段（直接装：.venv 里的；Docker：容器里的）。PYRUN 下面按装法填
pyrun() { "${PYRUN[@]}" "$@"; }

# 账本里一个人都没有？没有账本 ＝ 没有人。
# **不走 ORM**：这时候表结构可能还没升级（服务还没起来），新代码的 select(Member) 会点名
# 一个还不存在的列、查询报错 —— 报错原来被当成「没人」，升级时就会问「要不要导入旧账本」。
# 用标准库 sqlite3 直接数，而且**读不出来就当有人**：宁可少问一句，别在真账本上走「首次部署」
# </dev/null：docker compose run/exec 默认接着标准输入，不关掉的话会把人接下来要回答的那几行吃掉
nobody() {
  [ -f "$DB" ] || return 0
  [ "$(pyrun -c 'import sqlite3; c = sqlite3.connect("file:data/nagaya.db?mode=ro", uri=True); print(1 if c.execute("select count(*) from member").fetchone()[0] == 0 else 0)' 2>/dev/null </dev/null || echo 0)" = 1 ]
}

# 看一眼（给了参数就改成它）备份目录：能不能建、能不能写、是不是落在对外发的前端目录里。
# 输出「OK<TAB>绝对路径」或「BAD<TAB>原值<TAB>原因」
backup_check() {
  pyrun - "$@" <<'PYEOF'
import sys
from pathlib import Path
from sqlmodel import Session
from app.db import engine
from app.services import backup as backup_svc
from app.services import settings as settings_svc

import os

web = (Path.cwd().parent / "frontend").resolve()
in_docker = os.environ.get("NAGAYA_CONTAINER") == "1"   # Dockerfile 里设的：是跑在 nagaya 的镜像里
with Session(engine) as s:
    raw = sys.argv[1] if len(sys.argv) > 1 else str(settings_svc.get(s, "backup_path"))
    try:
        target = backup_svc.resolve_backup_path(raw)
        # 备份是整本账的明文：不许落在前端目录下面（那个目录整个对外发）
        if target == web or target.is_relative_to(web):
            raise ValueError("不能放在 frontend/ 下面（那个目录整个对外发）")
        # 服务是 ProtectSystem=full 跑的：这几处对它是只读的，备份会天天失败
        if not in_docker and any(target.is_relative_to(p) for p in ("/usr", "/etc", "/boot", "/efi")):
            raise ValueError("不能放在 /usr、/etc、/boot 下面（服务对那里没有写权限）")
        # **只建最后一级**（和备份服务自己一样）：外接盘、NAS 没挂上的时候，
        # 整条路径建到本机系统盘上、报一句「好了」—— 备份从此悄悄写在错的盘上
        created = not target.exists()
        target.mkdir(exist_ok=True)
        if created:
            target.chmod(0o700)
        # 容器里：这个目录得是挂出来的（和容器根目录不在同一个设备上），不然删容器备份就没了
        if in_docker and os.stat(target).st_dev == os.stat("/").st_dev:
            raise ValueError("这个目录没挂到宿主机上（docker-compose.yml 里加一行 volumes），删容器就没了")
        probe = target / ".nagaya-write-test"
        probe.write_text("ok")
        probe.unlink()
    except Exception as e:  # noqa: BLE001
        print(f"BAD\t{raw}\t{e}")
        sys.exit(0)
    if len(sys.argv) > 1:
        # 相对路径原样存（./backups）：换台机器、挪了仓库也还指着仓库里的那个目录
        settings_svc.set_(s, "backup_path", raw if not Path(raw).expanduser().is_absolute() else str(target))
    print(f"OK\t{target}")
PYEOF
}

# 问要不要搬旧账本，要的话把那份备份按恢复工具认的名字放好，回显它的名字（不要就回显空）
ask_import() {
  interactive || return 0
  say "" >&2
  say "要从旧机器搬账本过来吗？给一份**备份文件**的路径（旧机器上「设置 → 备份 → 立即备份」" >&2
  say "产出的 nagaya-*.db）。别直接拷旧机器的 data/nagaya.db：没 checkpoint 的数据在 -wal 里，会丢。" >&2
  local src=''
  while :; do
    ask src "备份文件路径（回车跳过，从空账本开始）" ""
    [ -n "$src" ] || return 0
    # 拖进终端的路径会带引号或者反斜杠转义的空格；~ 也得自己展开（read 不管）
    src="${src%\"}"; src="${src#\"}"; src="${src%\'}"; src="${src#\'}"; src="${src//\\ / }"
    case "$src" in "~"*) src="$HOME${src#\~}" ;; esac
    case "$src" in /*) ;; *) src="$ORIG_PWD/$src" ;; esac
    [ -f "$src" ] && break
    say "⚠ 没有这个文件：$src" >&2
  done
  # 恢复工具只认 nagaya-YYYYMMDD-HHMMSS.db 这种名字：按规矩起个名，放进备份目录
  local name; name="nagaya-$(date +%Y%m%d-%H%M%S).db"
  mkdir -p "$BACKEND/backups"
  cp "$src" "$BACKEND/backups/$name"
  printf '%s' "$name"
}

wait_healthy() {
  for _ in $(seq 1 60); do
    curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

# 库里没人：问要不要现在建第一个账号（密码在 add_member 自己那儿输两遍，不经过这个脚本）
first_account() {
  nobody || return 0
  if interactive && confirm "库里还没有人。现在建第一个账号吗？"; then
    local login='' display=''
    while [ -z "$login" ]; do ask login "登录名（英文、数字）" ""; done
    ask display "显示名（界面上叫什么）" "$login"
    until "${ACCOUNT[@]}" "$login" "$display"; do
      confirm "没建成（上面有原因），再试一次？" || { say "⚠ 之后手动建：${ACCOUNT_HINT}"; break; }
    done
  else
    say "⚠ 库里还没有人。建第一个账号：${ACCOUNT_HINT}"
  fi
}

# ======================================================================= Docker
deploy_docker() {
  command -v docker >/dev/null         || die "没有 docker。先装 Docker（群晖：套件中心里的 Container Manager）"
  docker compose version >/dev/null 2>&1 || die "没有 docker compose（要 v2 的 docker compose，不是老的 docker-compose）"
  command -v curl >/dev/null           || die "没有 curl（用来确认服务起来了）"
  cd "$APP"
  # 容器起来之前（看账本里有没有人、导入旧账本）用一次性容器；起来之后进正在跑的那个
  PYRUN=(docker compose run --rm -T --no-deps nagaya .venv/bin/python)
  ACCOUNT=(docker compose exec nagaya .venv/bin/python -m tools.add_member)
  ACCOUNT_HINT="docker compose exec nagaya .venv/bin/python -m tools.add_member <登录名> <显示名>"

  # 端口：.env 里有就沿用（升级不问：换端口的话手机主屏上那个图标就作废了）
  local envf="$APP/.env" prev
  prev="$(sed -n 's/^NAGAYA_PORT=\([0-9]*\)$/\1/p' "$envf" 2>/dev/null | head -1 || true)"
  if [ -z "${PORT:-}" ]; then
    if [ -n "$prev" ]; then PORT="$prev"; else ask PORT "服务端口（前端和接口同一个端口）" "$PORT_DEFAULT"; fi
  fi
  check_port

  # 账本和备份放在宿主机上。先自己把目录建出来 —— 让 docker 去建的话是 root 的；
  # 容器就以这两个目录主人的身份跑，文件在宿主机上归你，不用 sudo 才打得开
  mkdir -p "$BACKEND/data" "$BACKEND/backups"
  local owner; owner="$(ls -nd "$BACKEND/data" | awk '{print $3":"$4}')"
  { grep -vE '^NAGAYA_(PORT|UID|GID)=' "$envf" 2>/dev/null || true
    printf 'NAGAYA_PORT=%s\nNAGAYA_UID=%s\nNAGAYA_GID=%s\n' "$PORT" "${owner%%:*}" "${owner##*:}"
  } > "$envf.tmp"
  mv "$envf.tmp" "$envf"
  say "✔ 端口 ${PORT}，容器以 uid:gid $owner 的身份写文件（记在 .env 里）"

  say "→ 打镜像（第一次要下 Node 和 Python 的底包，几分钟）…"
  docker compose build

  # 第一次：搬旧账本。要在容器起来之前做 —— 起来了它就建好一本空账本了
  local first=0 imported=''
  if nobody; then first=1; fi
  if [ "$first" = 1 ]; then
    imported="$(ask_import)"
    if [ -n "$imported" ]; then
      docker compose stop nagaya >/dev/null 2>&1 || true
      # 恢复工具会先验这份备份、把拷贝升到现在的表结构再装上；升不上来就停，什么都不动
      docker compose run --rm -T --no-deps nagaya .venv/bin/python -m tools.restore \
        --dir=/app/backend/backups --yes "$imported" </dev/null \
        || die "这份备份导入失败（上面有原因）"
    fi
  fi

  docker compose up -d
  PYRUN=(docker compose exec -T nagaya .venv/bin/python)
  wait_healthy || { say "❌ 容器起来了，但端口 ${PORT} 没有应答。最近的日志："; docker compose logs --tail 40 nagaya; exit 1; }
  say "✔ 服务起来了"

  # 导入的旧账本里记着旧机器的备份目录（多半是那台的路径），容器里用不了：改回挂出来的那个。
  # 升级时不替人改：可能只是 NAS 那个共享这会儿没挂上，设置页上会报出来
  local bk; bk="$(backup_check)"
  if [ "${bk%%$'\t'*}" = BAD ]; then
    if [ "$first" = 1 ]; then
      say "⚠ 账本里记着的备份目录在容器里用不了（$(printf '%s' "$bk" | cut -f2)），改回 backend/backups"
      bk="$(backup_check ./backups)"
    else
      say "⚠ 现在设的备份目录用不了：$(printf '%s' "$bk" | cut -f2-) —— 没替你改，去「设置 → 备份」看一眼"
    fi
  fi

  first_account

  local ip; ip="$(local_ip | head -1)"
  say ""
  say "✅ 部署完成 → http://${ip:-<这台机器的IP>}:${PORT}"
  say ""
  say "   手机：Safari 打开上面的地址 → 登录 → 更多 → 设置 → 最底下「添加到主屏幕」照着做。"
  say "   账本：$BACKEND/data     备份：$BACKEND/backups（每天自动一份）"
  say "         想把备份放到 NAS 的别的共享目录：在 docker-compose.yml 里再挂一个目录，设置里填容器里的路径。"
  say "   ⚠ 这是局域网里的 http；出门在外要用，前面套一层 HTTPS，见 README「HTTPS」。"
  say ""
  say "   日志: docker compose logs -f     重启: docker compose restart"
  say "   升级: git pull && bash deploy.sh --docker"
}

if [ "${1:-}" = "--docker" ]; then
  deploy_docker
  exit 0
fi

# ======================================================================= 直接装（systemd）
[ "$(uname -s)" = Linux ]       || die "直接装只给 Linux（systemd）用。别的系统：bash deploy.sh --docker，或者 cd backend && ./run.sh"
[ "$(id -u)" -eq 0 ]            || die "需要 root（要写 /etc/systemd/system、装依赖）。用 Docker 的话：bash deploy.sh --docker"
command -v systemctl >/dev/null || die "没有 systemd。用 Docker：bash deploy.sh --docker；或者手动 cd backend && nohup ./run.sh > nagaya.log 2>&1 &"
# 服务是 ProtectSystem=full 跑的，这几处对它只读：账本一写就失败
case "$APP/" in /usr/*|/etc/*|/boot/*|/efi/*) die "仓库别放在 /usr、/etc、/boot 下面（服务对那里没有写权限），挪到 /opt 或 /srv" ;; esac
# 这个脚本只管默认位置的账本（backend/data/nagaya.db）。环境里指着别处的话，
# 下面看「有没有人」、导入、改设置用的是那一份，服务开的却是这一份 —— 两边对不上
[ -z "${NAGAYA_DB:-}" ] || die "环境里设着 NAGAYA_DB=${NAGAYA_DB}：deploy.sh 只管 backend/data/nagaya.db。先 unset NAGAYA_DB 再跑"
say "✔ 项目目录：$APP"
PYRUN=("$BACKEND/.venv/bin/python")
ACCOUNT=("$BACKEND/.venv/bin/python" -m tools.add_member)
ACCOUNT_HINT="cd $BACKEND && .venv/bin/python -m tools.add_member <登录名> <显示名>"

# ---- 已经有一个 nagaya 服务的话，先看它是不是这一份 ---------------------------------------
UNIT="/etc/systemd/system/${SVC}.service"
MARK="# 由 nagaya 的 deploy.sh 生成"
if [ -f "$UNIT" ]; then
  OLD_DIR="$(sed -n 's/^WorkingDirectory=//p' "$UNIT" | head -1)"
  # 指着别的目录（另一份克隆、手动装的那份）：那边的账本不会跟过来。照写的话服务会开一本空账本，
  # 室友看见的是一个什么都没有的 app，真账本在旧位置上没人管
  if [ -n "$OLD_DIR" ] && [ "$OLD_DIR" != "$BACKEND" ]; then
    die "已经有一个 nagaya 服务指着 ${OLD_DIR}（不是这一份）。要换位置：在那边「设置 → 备份 → 立即备份」，停掉旧服务（systemctl disable --now ${SVC}），再回来重跑，第一次部署时导入那份备份"
  fi
  if grep -qE '^Environment=NAGAYA_DB=|^User=' "$UNIT"; then
    die "$UNIT 里设着 NAGAYA_DB 或 User=（手动配过的），这个脚本会把它们冲掉。先按那边的配置处理好（或者删掉这个文件）再跑"
  fi
  if ! grep -qF "$MARK" "$UNIT" && ! confirm "$UNIT 不是这个脚本写的，要替换成新的吗？"; then
    die "没动。"
  fi
fi

# ---- 端口（升级时沿用上次的：换端口的话手机主屏上那个图标就作废了）------------------
PREV_PORT="$(sed -n 's/^Environment=PORT=\([0-9]*\)$/\1/p' "$UNIT" 2>/dev/null | head -1 || true)"
if [ -z "${PORT:-}" ]; then
  if [ -n "$PREV_PORT" ]; then PORT="$PREV_PORT"; else ask PORT "服务端口（前端和接口同一个端口）" "$PORT_DEFAULT"; fi
fi
check_port
# 被别的程序占着的话，服务起来就是一直崩溃重启 —— 在这儿就说清楚
if command -v ss >/dev/null && ss -ltnH "( sport = :$PORT )" 2>/dev/null | grep -q . \
   && ! systemctl is-active --quiet "$SVC"; then
  die "端口 $PORT 已经被别的程序占了（ss -ltnp 看是谁），换一个：PORT=xxxx bash deploy.sh"
fi
say "✔ 端口：${PORT}"

# ---- 系统依赖：只装缺的 ------------------------------------------------------------
need=()
command -v curl >/dev/null || need+=(curl ca-certificates)
command -v xz   >/dev/null || need+=(xz-utils)          # Node 的包是 .tar.xz
if [ "${#need[@]}" -gt 0 ]; then
  command -v apt-get >/dev/null || die "缺 ${need[*]}，而这台机器没有 apt-get，先手动装上"
  say "→ 安装 ${need[*]} …"
  apt-get update -qq
  apt-get install -y -qq "${need[@]}"
fi

# ---- Node + 打包前端（**先做这一段**：下载、装依赖、打包是最容易半路失败的，
#      做在前面的话，失败时后端和正在跑的服务一点都没动过）-------------------------------
TOOLS="$APP/.tools"
export PATH="$TOOLS/node/bin:$PATH"
node_ok() {
  # 要 node 也要 npm：Debian / Ubuntu 的 nodejs 和 npm 是分开的两个包
  command -v node >/dev/null && command -v npm >/dev/null && node -e '
    const [a, b] = process.versions.node.split(".").map(Number)
    process.exit(a > 22 || (a === 22 && b >= 12) ? 0 : 1)'
}
if ! node_ok; then
  case "$(uname -m)" in
    x86_64) NARCH=x64 ;;
    aarch64|arm64) NARCH=arm64 ;;
    *) die "不认识的 CPU 架构 $(uname -m)：手动装 Node 22.12+ 再重跑，或者用 --docker" ;;
  esac
  say "→ 安装 Node ${NODE_MAJOR}（放在 $TOOLS/node，不动系统）…"
  BASE="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"
  SUMS="$(curl -fsSL "$BASE/SHASUMS256.txt")" || die "取不到 Node 的版本清单，检查能否联网"
  LINE="$(printf '%s\n' "$SUMS" | grep -E "  node-v[0-9.]+-linux-${NARCH}\.tar\.xz$" | head -1 || true)"
  [ -n "$LINE" ] || die "nodejs.org 上没有 linux-$NARCH 的 Node $NODE_MAJOR"
  FILE="${LINE##* }"
  TMP="$(mktemp -d)"
  curl -fsSL "$BASE/$FILE" -o "$TMP/$FILE" || die "下载 Node 失败"
  # 校验：下了一半、被中间人换掉的包，装上去就是一个跑不起来（或者更糟）的 node
  (cd "$TMP" && printf '%s\n' "$LINE" | sha256sum -c --quiet -) || die "Node 安装包校验没过"
  rm -rf "$TOOLS/node"
  mkdir -p "$TOOLS"
  tar -xJf "$TMP/$FILE" -C "$TOOLS"
  mv "$TOOLS/${FILE%.tar.xz}" "$TOOLS/node"
  # bash 记着上一次在哪找到的 node（系统里那个太旧的）：不清掉的话下面用的还是它
  hash -r
fi
node_ok || die "Node 没装好（要 22.12 以上，而且要有 npm）"
say "✔ Node $(node -v)"

cd "$FRONTEND"
# 依赖没变就不重装：npm ci 每次都把 node_modules 整个删了重下，一两分钟
LOCK_SUM="$(sha256sum package-lock.json | cut -d' ' -f1)"
if [ "$(cat node_modules/.nagaya-lock 2>/dev/null || true)" != "$LOCK_SUM" ]; then
  say "→ 安装前端依赖 …"
  npm ci --no-audit --no-fund --loglevel=error
  printf '%s\n' "$LOCK_SUM" > node_modules/.nagaya-lock
fi
say "→ 打包前端 …"
# 打包的进度一屏一屏地刷，只在失败时才摆出来
BUILD_LOG="$(mktemp)"
if ! npm run build --silent > "$BUILD_LOG" 2>&1; then
  tail -40 "$BUILD_LOG"
  die "前端打包失败（上面是最后几十行）"
fi
rm -f "$BUILD_LOG"
[ -f dist/pwa/index.html ] || die "前端没打包出来（frontend/dist/pwa/index.html 不在）"
say "✔ 前端打包好了"

# ---- uv + Python + 后端依赖 ----------------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  say "→ 安装 uv …"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null || die "uv 安装失败，检查能否联网"
say "✔ uv $(uv --version)"

cd "$BACKEND"
uv python install "$PYVER"
# 【只在没有 venv、或者版本不对时才重建】重建会把整个目录换掉 ——
# 升级时在还在跑的服务脚下抽掉 site-packages。依赖有变化装进现有环境就够了。
# 要重建就先停服务（这一趟停的，半路失败时 cleanup 会替人起回来）
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -V 2>/dev/null | grep -q " $PYVER"; then
  stop_service
  uv venv --clear --python "$PYVER"
fi
# 装钉死的那一组（requirements.lock）：requirements.txt 只写下限，新机器上会装到不兼容的新版
uv pip install --python .venv/bin/python -q -r requirements.lock
PY="$BACKEND/.venv/bin/python"
"$PY" -c "import fastapi, uvicorn, sqlmodel, alembic, PIL, jwt, bcrypt, multipart" \
  || die "后端依赖没装全"
say "✔ 后端依赖 OK（$("$PY" -V)）"

# ---- 第一次部署：要不要把旧账本搬过来 --------------------------------------------------
# 「第一次」＝ 没有账本、或者账本里一个人都没有（上一次部署半路失败留下的空账本也算）
FIRST=0
if nobody; then FIRST=1; fi
if [ "$FIRST" = 1 ]; then
  IMPORTED="$(ask_import)"
  if [ -n "$IMPORTED" ]; then
    stop_service                                 # 恢复工具要求服务停着，不然它还在往旧库里写
    # 它会先验这份备份、把拷贝升到现在的表结构，再装上去；升不上来就停，什么都不动
    "$PY" -m tools.restore --dir="$BACKEND/backups" --yes "$IMPORTED" || die "这份备份导入失败（上面有原因）"
  fi
fi

# ---- systemd ---------------------------------------------------------------------------
# 起服务走 run.sh（和手动起同一条路，带着 umask 077：账本、签名密钥只有自己能读）
cat > "$UNIT" <<EOF
${MARK}（改了会在下次部署时被覆盖）
[Unit]
Description=nagaya
After=network-online.target
Wants=network-online.target
# 5 分钟里起不来 5 次就别再试了：比如新版的表结构升级在这本账本上失败 ——
# 每次重启都会先拍一张升级前的快照，无限重启会把盘写满
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
WorkingDirectory=$BACKEND
Environment=PORT=$PORT
# stdout 不是终端时 Python 会攒 8KB 再写，journalctl -f 里日志一批一批地迟到
Environment=PYTHONUNBUFFERED=1
ExecStart=$BACKEND/run.sh
Restart=always
RestartSec=5
# 只写自己的 data/ 和备份目录；备份目录能在设置里改到任何地方（外接盘、NAS 共享），
# 所以不收 ProtectHome、不收写权限 —— 收了的话备份会在某天悄悄开始失败
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SVC" >/dev/null 2>&1 || true
systemctl reset-failed "$SVC" 2>/dev/null || true
systemctl restart "$SVC"
STOPPED=0                                        # 起过了：后面再失败就不关 cleanup 的事

# is-active 不够：Restart=always 时崩溃循环里也会短暂是 active。真去打一次接口。
# 等得久一点：表结构升级（大库要整表重建）在开机时做
if ! wait_healthy; then
  say "❌ 服务没起来，或者端口 ${PORT} 没有应答。最近的日志："
  journalctl -u "$SVC" -n 40 --no-pager || true
  # 停掉，别让它一直重启（每次重启都可能拍一张升级前的快照）
  systemctl stop "$SVC" 2>/dev/null || true
  say "服务已经停下。修好之后重跑 deploy.sh；账本没动过，升级前的快照在 $BACKEND/data/before-migrate-*.db"
  exit 1
fi
say "✔ 服务起来了"

# ---- 备份放哪 --------------------------------------------------------------------------
# 第一次部署问；现在设的目录用不了（导入的旧账本里记着旧机器的路径、外接盘没挂上）时也问。
# 问不了人的时候：第一次就用默认的；升级时**不替人改**，只提醒（可能只是盘这会儿没挂上）
BK="$(backup_check)"
BK_STATE="${BK%%$'\t'*}"
if [ "$FIRST" = 1 ] || [ "$BK_STATE" = BAD ]; then
  if [ "$BK_STATE" = BAD ]; then
    say "⚠ 现在设的备份目录用不了：$(printf '%s' "$BK" | cut -f2-)"
  fi
  if interactive; then
    say ""
    say "备份每天自动做一份。放在和账本同一块盘上防得住手滑，防不住盘坏 ——"
    say "有外接盘或 NAS 共享目录的话，填那个路径（绝对路径；只建最后一级目录，外接盘得先挂好）。"
    while :; do
      if [ "$FIRST" = 1 ]; then
        ask BK_DIR "备份目录（回车用 backend/backups）" ""
        BK_DIR="${BK_DIR:-./backups}"
      else
        ask BK_DIR "新的备份目录（回车＝先不改，之后去设置里改）" ""
        [ -n "$BK_DIR" ] || break
      fi
      BK="$(backup_check "$BK_DIR")"
      [ "${BK%%$'\t'*}" = OK ] && break
      say "⚠ 用不了：$(printf '%s' "$BK" | cut -f3-)"
    done
  elif [ "$FIRST" = 1 ] && [ "$BK_STATE" = BAD ]; then
    BK="$(backup_check ./backups)"
  fi
fi
if [ "${BK%%$'\t'*}" = OK ]; then
  BACKUP_LINE="每天自动一份 → $(printf '%s' "$BK" | cut -f2)（份数、间隔在「系统设置」里改）"
  say "✔ 备份目录：$(printf '%s' "$BK" | cut -f2)"
else
  BACKUP_LINE="⚠ 备份目录现在用不了（$(printf '%s' "$BK" | cut -f2)），去「设置 → 备份」改"
fi

first_account

# ---- 说清楚怎么用 ----------------------------------------------------------------------
IP="$(local_ip | head -1)"
say ""
say "✅ 部署完成 → http://${IP:-<这台机器的IP>}:${PORT}"
say ""
say "   手机：Safari 打开上面的地址 → 登录 → 更多 → 设置 → 最底下「添加到主屏幕」照着做。"
say "         要改 App 的名字和图标，先在「应用设置」里改好再加（加的那一刻就定了）。"
say "   室友：更多 → 设置 → 成员 → 加一个人（或者 ${ACCOUNT_HINT}）"
say "   备份：${BACKUP_LINE}"
say "   ⚠ 这是局域网里的 http：出门在外要用、或者想要离线冷启动，前面套一层 HTTPS"
say "     （Tailscale serve / Cloudflare Tunnel / Caddy），见 README「HTTPS」。"
say ""
say "   日志: journalctl -u ${SVC} -f     重启: systemctl restart ${SVC}"
say "   升级: cd $APP && git pull && bash deploy.sh"
say "   恢复: systemctl stop ${SVC}; (cd $BACKEND && .venv/bin/python -m tools.restore); systemctl start ${SVC}"
