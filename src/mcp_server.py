"""
Zenithfall Photo Alchemy - MCP Protocol Server v3
ChatGPT Apps SDK 対応版（gift統合、3ターン探索、消失システム対応）

MCPプロトコル仕様:
- JSON-RPC 2.0 ベース
- initialize / initialized ハンドシェイク
- tools/list でツール一覧
- tools/call でツール実行
"""
from __future__ import annotations

import os
import sys
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

# srcディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(__file__))

from config import DEBUG_MODE, JST, GameLimits
from game_engine import get_engine

# ========================================
# ロギング設定
# ========================================
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp_server")

# ========================================
# MCP プロトコル設定
# ========================================
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "zenithfall-photo-alchemy"
SERVER_VERSION = "0.3.0"  # SSE対応版

# ========================================
# FastAPI App
# ========================================
app = FastAPI(
    title="Zenithfall Photo Alchemy MCP Server",
    version=SERVER_VERSION,
)

# CORS設定（ChatGPTからのアクセス許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chatgpt.com",
        "https://chat.openai.com",
        "http://localhost:3000",  # 開発用
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "MCP-Protocol-Version"],
)

# ========================================
# ツール定義（giftツール削除済み）
# ========================================
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "start_run",
        "description": "ゲームを開始または再開します。新規プレイヤーは種族を選択してください。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "選択する種族ID（hume/sylva/felina/tigr/lupus）",
                    "enum": ["hume", "sylva", "felina", "tigr", "lupus"]
                },
                "partner_name": {
                    "type": "string",
                    "description": "相棒の名前（省略可）"
                },
                "force_new": {
                    "type": "boolean",
                    "description": "強制的に新規ゲームを開始するか",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "transmute_photo",
        "description": "写真を錬金素材に変換します。写真から材質・概念・品質を判定してください。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "detected_material": {
                    "type": "string",
                    "description": "判定した材質（10種）",
                    "enum": ["metal", "wood", "cloth", "leather", "stone_glass", "paper", "plastic", "organic", "ceramic", "liquid"]
                },
                "detected_essence": {
                    "type": "string",
                    "description": "判定した概念（12種）",
                    "enum": ["attack", "defense", "control", "time", "light", "dark", "heal", "knowledge", "move", "preserve", "destroy", "create"]
                },
                "detected_quality": {
                    "type": "integer",
                    "description": "判定した品質（1-5）",
                    "minimum": 1,
                    "maximum": 5
                },
                "hint_text": {
                    "type": "string",
                    "description": "写真の説明（例：鍵を撮った）"
                }
            },
            "required": ["detected_material", "detected_essence", "detected_quality"]
        }
    },
    {
        "name": "craft_item",
        "description": "素材からアイテムを錬金（生成）します。通常生成とギフト生成を選べます。ギフト生成は即時相棒に渡され、好感度が上昇します。1日3回まで（通常/ギフト共通）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "material_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "使用する素材のID配列"
                },
                "catalyst_id": {
                    "type": "string",
                    "description": "使用する触媒のID（省略可）"
                },
                "craft_type": {
                    "type": "string",
                    "description": "生成タイプ（normal:通常生成/gift:ギフト生成）",
                    "enum": ["normal", "gift"],
                    "default": "normal"
                }
            },
            "required": ["material_ids"]
        }
    },
    {
        "name": "explore",
        "description": "ダンジョンを探索します（1日1回）。3ターン制で、Turn1/2は通常敵、Turn3はボス戦。成功すると触媒がドロップし、最後に宝箱から2〜4個の追加素材を得られます。相棒が消失中は探索できません。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dungeon_id": {
                    "type": "string",
                    "description": "探索するダンジョンのID"
                },
                "style": {
                    "type": "string",
                    "description": "探索スタイル（heal:回復重視/guard:防御重視/none:通常）",
                    "enum": ["heal", "guard", "none"],
                    "default": "none"
                }
            },
            "required": ["dungeon_id"]
        }
    },
    {
        "name": "get_status",
        "description": "現在のゲーム状態を取得します。インベントリ、好感度、ランク、消失状態などを確認できます。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_available_dungeons",
        "description": "現在のランクで挑戦可能なダンジョン一覧を取得します。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_recipes",
        "description": "現在のランクで作成可能なレシピ一覧を取得します。ギフトレシピも含みます。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]

# デバッグ用ツール
if DEBUG_MODE:
    TOOLS.extend([
        {
            "name": "debug_reset_daily",
            "description": "[デバッグ] 日次制限をリセットします",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "debug_set_state",
            "description": "[デバッグ] 状態を直接設定します",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "phase": {"type": "integer", "minimum": 1, "maximum": 5},
                    "affection": {"type": "number", "minimum": 0, "maximum": 100},
                    "rank": {"type": "integer", "minimum": 1, "maximum": 5},
                    "is_vanished": {"type": "boolean"},
                    "has_revival_item": {"type": "boolean"}
                },
                "required": []
            }
        },
        {
            "name": "debug_force_vanish",
            "description": "[デバッグ] 相棒を強制的に消失状態にします",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    ])

# ========================================
# ユーザーID管理（簡易版）
# ========================================
def get_user_id(request: Request) -> str:
    """リクエストからユーザーIDを取得（MVPは簡易実装）"""
    # ヘッダーから取得を試みる
    user_id = request.headers.get("X-User-ID")
    if user_id:
        return user_id
    
    # なければデフォルト（MVP用）
    return "default-user"

# ========================================
# MCP JSON-RPC ハンドラー
# ========================================
def handle_initialize(params: Dict) -> Dict:
    """initializeリクエストの処理"""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {
            "logging": {},
            "tools": {"listChanged": False}
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "title": "Zenithfall Photo Alchemy",
            "version": SERVER_VERSION
        }
    }

def handle_tools_list(params: Dict) -> Dict:
    """tools/listリクエストの処理"""
    return {
        "tools": TOOLS
    }

def handle_tools_call(params: Dict, user_id: str) -> Dict:
    """tools/callリクエストの処理"""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    
    logger.info(f"Tool call: {tool_name} with args: {arguments}")
    
    engine = get_engine()
    
    try:
        # ツール実行
        if tool_name == "start_run":
            result = engine.start_run(user_id, arguments)
        elif tool_name == "transmute_photo":
            result = engine.transmute_photo(user_id, arguments)
        elif tool_name == "craft_item":
            result = engine.craft_item(user_id, arguments)
        elif tool_name == "explore":
            result = engine.explore(user_id, arguments)
        elif tool_name == "get_status":
            result = engine.get_status(user_id, arguments)
        elif tool_name == "get_available_dungeons":
            result = engine.get_available_dungeons(user_id, arguments)
        elif tool_name == "get_recipes":
            result = engine.get_recipes(user_id, arguments)
        elif tool_name == "debug_reset_daily" and DEBUG_MODE:
            result = engine.debug_reset_daily(user_id)
        elif tool_name == "debug_set_state" and DEBUG_MODE:
            result = engine.debug_set_state(user_id, arguments)
        elif tool_name == "debug_force_vanish" and DEBUG_MODE:
            result = engine.debug_force_vanish(user_id)
        else:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True
            }
        
        # 結果をMCP形式に変換
        return format_tool_result(result)
        
    except Exception as e:
        logger.error(f"Tool call error: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"エラーが発生しました: {str(e)}"}],
            "isError": True
        }

def format_tool_result(result: Dict) -> Dict:
    """ゲームエンジンの結果をMCP形式に変換"""
    # メッセージを構築
    parts = []
    
    if result.get("message"):
        parts.append(result["message"])
    
    # 状態変更があれば追加
    state_patch = result.get("state_patch", {})
    if state_patch:
        # 重要な変更のみ表示
        if "affection" in state_patch:
            parts.append(f"（好感度: {state_patch['affection']:.1f}）")
        if "phase" in state_patch:
            parts.append(f"（Phase: {state_patch['phase']}）")
        if "is_vanished" in state_patch and state_patch["is_vanished"]:
            parts.append("⚠️ 相棒が消失状態です")
    
    # UI ヒント
    ui_hints = result.get("ui_hints", {})
    
    # 探索ログがあれば追加
    if "exploration_log" in ui_hints:
        for turn_log in ui_hints["exploration_log"]:
            if turn_log.get("message"):
                parts.append(f"  {turn_log['message']}")
    
    # 復活情報
    if ui_hints.get("revival") and ui_hints["revival"].get("revived"):
        parts.append(f"✨ {ui_hints['revival'].get('message', '相棒が復活した！')}")
    
    # Phase上昇
    if ui_hints.get("phase_up"):
        parts.append("🎉 Phaseが上がった！")
    
    text = "\n".join(parts) if parts else "OK"
    
    return {
        "content": [
            {
                "type": "text",
                "text": text
            }
        ],
        "isError": not result.get("ok", True),
        "_raw": result  # デバッグ用に生データも含める
    }

# ========================================
# JSON-RPC ディスパッチャー
# ========================================
def dispatch_jsonrpc(request_data: Dict, user_id: str) -> Dict:
    """JSON-RPC リクエストを処理"""
    method = request_data.get("method", "")
    params = request_data.get("params", {})
    request_id = request_data.get("id")
    
    logger.info(f"Dispatch: method={method}, id={request_id}")
    
    result = None
    error = None
    
    try:
        if method == "initialize":
            result = handle_initialize(params)
        elif method == "initialized":
            result = {}
        elif method == "tools/list":
            result = handle_tools_list(params)
        elif method == "tools/call":
            result = handle_tools_call(params, user_id)
        else:
            error = {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
    except Exception as e:
        logger.error(f"Dispatch error: {e}", exc_info=True)
        error = {
            "code": -32603,
            "message": str(e)
        }
    
    response = {"jsonrpc": "2.0"}
    
    if request_id is not None:
        response["id"] = request_id
    
    if error:
        response["error"] = error
    else:
        response["result"] = result
    
    return response

# ========================================
# エンドポイント
# ========================================
@app.get("/")
async def root():
    """ヘルスチェック"""
    return {
        "status": "ok",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "protocol": PROTOCOL_VERSION,
        "debug_mode": DEBUG_MODE,
    }

@app.get("/health")
async def health():
    """ヘルスチェック（Railway用）"""
    return {"status": "healthy"}

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCPプロトコルエンドポイント（SSE対応 - ChatGPT Apps SDK用）"""
    user_id = get_user_id(request)
    
    try:
        body = await request.json()
        logger.debug(f"MCP Request: {json.dumps(body, ensure_ascii=False)[:500]}")
    except Exception as e:
        # パースエラーもSSE形式で返す
        async def error_stream():
            error_response = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None
            }
            yield f"data: {json.dumps(error_response)}\n\n"
        
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
    
    async def generate():
        # バッチリクエスト対応
        if isinstance(body, list):
            for req in body:
                response = dispatch_jsonrpc(req, user_id)
                logger.debug(f"MCP Response: {json.dumps(response, ensure_ascii=False)[:500]}")
                yield f"data: {json.dumps(response, ensure_ascii=False)}\n\n"
        else:
            response = dispatch_jsonrpc(body, user_id)
            logger.debug(f"MCP Response: {json.dumps(response, ensure_ascii=False)[:500]}")
            yield f"data: {json.dumps(response, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# 従来のJSONエンドポイント（デバッグ・curl用に残す）
@app.post("/mcp/json")
async def mcp_json_endpoint(request: Request):
    """MCPプロトコルエンドポイント（JSON形式 - デバッグ用）"""
    user_id = get_user_id(request)
    
    try:
        body = await request.json()
        logger.debug(f"MCP JSON Request: {json.dumps(body, ensure_ascii=False)[:500]}")
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None
            }
        )
    
    # バッチリクエスト対応
    if isinstance(body, list):
        responses = [dispatch_jsonrpc(req, user_id) for req in body]
        return JSONResponse(content=responses)
    else:
        response = dispatch_jsonrpc(body, user_id)
        logger.debug(f"MCP JSON Response: {json.dumps(response, ensure_ascii=False)[:500]}")
        return JSONResponse(content=response)

# ========================================
# メイン
# ========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "mcp_server:app",
        host="0.0.0.0",
        port=port,
        reload=DEBUG_MODE
    )
