#!/bin/bash
# =============================================================================
# PAgent 一键部署脚本
# 在 VPS 上运行：bash deploy/setup.sh
# =============================================================================
set -e

echo "=============================="
echo "  PAgent 部署脚本"
echo "=============================="
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 1. Python 环境
echo "[1/6] 检查 Python..."
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v $cmd &>/dev/null; then
        VER=$($cmd --version 2>&1 | grep -oP '\d+\.\d+')
        MAJOR=${VER%.*}
        MINOR=${VER#*.}
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON=$(command -v $cmd)
            echo "  ✅ 使用: $PYTHON ($($PYTHON --version))"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ⚠️  Python >= 3.9 未安装，正在安装..."
    apt update -qq && apt install -y -qq python3 python3-venv python3-pip
    PYTHON=$(command -v python3)
    echo "  ✅ 已安装: $PYTHON ($($PYTHON --version))"
fi

# 2. 虚拟环境
echo "[2/6] 创建虚拟环境..."
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/activate" ]; then
    rm -rf .venv
    $PYTHON -m venv .venv
    echo "  ✅ 已创建 .venv"
else
    echo "  ✅ .venv 已存在"
fi
source .venv/bin/activate

# 3. 依赖
echo "[3/6] 安装依赖..."
pip install --quiet --upgrade pip
pip install --quiet \
    ccxt pydantic numpy pandas openai tiktoken jsonschema cryptography
# Web 框架：锁定已知兼容版本（Jinja2 >= 3.1.3 与 Starlette 缓存机制冲突）
pip install --quiet "jinja2<3.1.3" "fastapi>=0.110" "uvicorn" "aiofiles" "python-multipart"
echo "  ✅ 依赖安装完成"

# 4. 数据目录
echo "[4/6] 创建数据目录..."
mkdir -p logs records/pending
echo "  ✅ 目录已就绪"

# 5. .env 文件
echo "[5/6] 检查 .env..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "  ⚠️  已从 .env.example 创建 .env 模板"
        echo "  ⚠️  请编辑 .env 填入 API Key：nano .env"
    fi
else
    echo "  ✅ .env 已存在"
fi

# 6. systemd 服务
echo "[6/6] 安装 systemd 服务..."
SERVICE_SRC="deploy/pa-web.service"
SERVICE_DST="/etc/systemd/system/pa-web.service"

# 替换工作目录为实际路径
sed "s|/opt/PAgent|$PROJECT_DIR|g" "$SERVICE_SRC" > /tmp/pa-web.service

if [ -f "$SERVICE_DST" ]; then
    systemctl daemon-reload
    systemctl restart pa-web
    echo "  ✅ 服务已重启"
else
    cp /tmp/pa-web.service "$SERVICE_DST"
    systemctl daemon-reload
    systemctl enable pa-web
    systemctl start pa-web
    echo "  ✅ 服务已安装并启动"
fi

rm -f /tmp/pa-web.service

echo ""
echo "=============================="
echo "  部署完成!"
echo "=============================="
echo ""
echo "  Web Dashboard:  http://$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):8080"
echo ""
echo "  后续步骤:"
echo "    1. 编辑 .env 填入 API Key:  nano .env"
echo "    2. 重启服务:                 systemctl restart pa-web"
echo "    3. 查看日志:                 journalctl -u pa-web -f"
echo "    4. 浏览器打开上面地址"
echo ""
