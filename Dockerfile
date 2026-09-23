# 長屋 nagaya 的 Docker 镜像（NAS、或者任何装了 Docker 的机器）。
# 裸机 / LXC 用仓库根目录的 deploy.sh；用 Docker 的话：
#
#   bash deploy.sh --docker          一键：问端口、起容器、建第一个账号
#   docker compose up -d --build     或者直接这一句（第一次和每次 git pull 之后都一样）
#
# 两段：先用 Node 把前端打成静态文件，再放进只有 Python 的运行镜像 —— Node 不进最终镜像。
# 账本、签名密钥、升级前的快照在 /app/backend/data，备份在 /app/backend/backups：
# 两个都挂到宿主机上（docker-compose.yml 里挂好了），删容器、重建镜像都不会碰它们。

FROM node:24-slim AS web
WORKDIR /app/frontend
# 先只拷依赖清单：代码改了、依赖没变时，这一层用缓存，不用每次重下
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --loglevel=error
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NAGAYA_CONTAINER=1
WORKDIR /app/backend
COPY backend/requirements.lock ./
# 装钉死的那一组（requirements.lock），不装 requirements.txt：那份只写下限，会装到不兼容的新版。
# 装进 .venv：启动走 run.sh，和裸机上是同一个脚本（它认的是 .venv/bin/uvicorn，还带着 umask 077）
RUN python -m venv .venv && .venv/bin/pip install --no-cache-dir -q -r requirements.lock
COPY backend/ ./
COPY --from=web /app/frontend/dist/pwa /app/frontend/dist/pwa

VOLUME ["/app/backend/data", "/app/backend/backups"]
EXPOSE 8000
# 开机时表结构升级（大库要整表重建）可能要一会儿，start-period 给足
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD .venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["./run.sh"]
