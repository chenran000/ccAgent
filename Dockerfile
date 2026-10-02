# ===== Stage 1: 前端构建 =====
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install --no-audit --no-fund
COPY frontend-react/ ./
RUN npm run build
# 产物目录: /frontend (vite outDir=../frontend,相对 vite 根解析)

# ===== Stage 2: 后端运行镜像 =====
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright

WORKDIR /app

# 系统依赖: xvfb+xauth 虚拟显示(有头浏览器兼容)、中文字体、curl 健康检查
# apt 源切换到清华镜像(deb.debian.org 国内极慢)
RUN sed -i 's@deb.debian.org@mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        xvfb xauth curl fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖(已移除本地 torch/bge 模型,Embedding 走 API)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium(含系统依赖库)
RUN playwright install --with-deps chromium

# 应用代码与前端产物
COPY app/ ./app/
COPY main.py .
COPY --from=frontend /frontend ./frontend

# 非 root 用户运行(Chromium 沙箱兼容)
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 2222

# 虚拟显示承载有头浏览器(headless=False 时);屏幕 1920x1080 保证整页截图完整。
# 不用 xvfb-run:其依赖 Xvfb 发 SIGUSR1 就绪信号,而子 shell 里 trap '' 已把 USR1
# 置为忽略,Xvfb 永远不通知父进程,作为 PID 1 时会永久死锁在 wait。
ENTRYPOINT ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp & sleep 1 && DISPLAY=:99 exec python main.py"]
