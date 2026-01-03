#!/bin/bash
# Zenithfall Photo Alchemy - Debug Mode Launcher

cd "$(dirname "$0")"

# デバッグモード有効化
export DEBUG_MODE=true

# データディレクトリ設定
export ZENITHFALL_DATA_DIR="./data"

echo "==================================="
echo "Zenithfall Photo Alchemy API"
echo "DEBUG MODE: ON"
echo "==================================="
echo ""
echo "Endpoints:"
echo "  GET  /           - Health check"
echo "  GET  /tools      - List available tools"
echo "  POST /tools/start_run"
echo "  POST /tools/transmute_photo"
echo "  POST /tools/craft_item"
echo "  POST /tools/explore"
echo "  POST /tools/gift"
echo ""
echo "Debug Endpoints:"
echo "  POST /debug/reset_daily"
echo "  POST /debug/set_state"
echo "  GET  /debug/state/{user_id}"
echo ""
echo "Swagger UI: http://localhost:8000/docs"
echo "==================================="
echo ""

cd src
python -m uvicorn mcp_server:app --reload --port 8000
