#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../frontend"
echo "正在安装前端依赖..."
npm ci
echo "正在构建前端..."
npm run build
echo "构建完成：$(pwd)/dist/"
