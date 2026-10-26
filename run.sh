#!/usr/bin/env bash
# 备课智能体 v2 · 一键启动（本地单机）
set -e
cd "$(dirname "$0")"

# 1) 安装依赖（首次）
if [ ! -d ".venv" ]; then
  echo "[1/3] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

# 2) 检查密钥配置
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[2/3] 已生成 .env（未填 Key = 演示模式）。如需真实调用，请编辑 .env 填入 LLM_API_KEY。"
else
  echo "[2/3] 使用现有 .env"
fi

# 3) 启动
echo "[3/3] 启动服务 → 浏览器打开 http://127.0.0.1:${PORT:-8000}"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
