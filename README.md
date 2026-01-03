# Zenithfall Photo Alchemy - Game Server

## 概要

写真を撮って異世界素材に変換し、装備やギフトを錬金するRPG「ゼニスフォール・フォト錬金術」のゲームサーバー。

## ファイル構成

```
photo_alchemy/
├── data/
│   ├── recipes_v1_0.json      # レシピ・触媒マスタ
│   ├── dungeons_v1_3.json     # ダンジョン・地域データ
│   ├── races_v1_2.json        # 種族・相棒データ
│   └── materials_schema.json  # 材質・概念スキーマ
├── src/
│   ├── config.py              # 設定・制限値
│   ├── game_engine.py         # コアロジック
│   └── mcp_server.py          # FastAPIサーバー
├── requirements.txt           # 依存ライブラリ
├── run_debug.sh              # デバッグ起動スクリプト
└── README.md
```

## セットアップ

```bash
# 1. 依存ライブラリインストール
pip install -r requirements.txt

# 2. デバッグモードで起動
chmod +x run_debug.sh
./run_debug.sh

# または手動で起動
cd src
DEBUG_MODE=true python -m uvicorn mcp_server:app --reload --port 8000
```

## API エンドポイント

### ゲームツール

| Method | Endpoint | 説明 |
|--------|----------|------|
| POST | `/tools/start_run` | 新規ゲーム開始 or 既存ロード |
| POST | `/tools/transmute_photo` | 写真→素材変換 |
| POST | `/tools/craft_item` | 素材→アイテム錬金 |
| POST | `/tools/explore` | ダンジョン探索 |
| POST | `/tools/gift` | ギフト贈呈 |

### デバッグツール（DEBUG_MODE=true 時のみ）

| Method | Endpoint | 説明 |
|--------|----------|------|
| POST | `/debug/reset_daily` | 日次カウンターリセット |
| POST | `/debug/set_state` | 状態を直接設定 |
| GET | `/debug/state/{user_id}` | 現在の状態取得 |

## 使用例

### 1. 新規ゲーム開始

```bash
curl -X POST http://localhost:8000/tools/start_run \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-001",
    "payload": {
      "race_id": "felina",
      "partner_name": "ミケ"
    }
  }'
```

### 2. 写真転生（デバッグ用ダミー入力）

```bash
curl -X POST http://localhost:8000/tools/transmute_photo \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-001",
    "payload": {
      "hint_text": "鍵を撮った",
      "detected_material": "metal",
      "detected_essence": "control",
      "detected_quality": 3
    }
  }'
```

### 3. 錬金

```bash
curl -X POST http://localhost:8000/tools/craft_item \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-001",
    "payload": {
      "material_ids": ["MAT-test-0001"]
    }
  }'
```

### 4. ダンジョン探索

```bash
curl -X POST http://localhost:8000/tools/explore \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-001",
    "payload": {
      "dungeon_id": "r1_training_grounds",
      "style": "guard"
    }
  }'
```

### 5. ギフト贈呈

```bash
curl -X POST http://localhost:8000/tools/gift \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-001",
    "payload": {
      "item_id": "ITM-test-0001"
    }
  }'
```

### デバッグ：日次リセット

```bash
curl -X POST http://localhost:8000/debug/reset_daily \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-001",
    "payload": {}
  }'
```

## 環境変数

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `DEBUG_MODE` | `false` | デバッグモード（制限解除） |
| `PORT` | `8000` | サーバーポート |
| `ZENITHFALL_DATA_DIR` | `./data` | データディレクトリ |

## Swagger UI

起動後、以下のURLでAPI仕様を確認できます：

http://localhost:8000/docs

## Railway デプロイ手順

### 1. GitHubにプッシュ

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/zenithfall-photo-alchemy.git
git push -u origin main
```

### 2. Railwayでデプロイ

1. [Railway](https://railway.app/) にログイン
2. 「New Project」→「Deploy from GitHub repo」
3. リポジトリを選択
4. 環境変数を設定:
   - `DEBUG_MODE` = `true`（開発時）
5. デプロイ完了を待つ

### 3. URLを取得

デプロイ完了後、Railwayが発行するURLをコピー:
```
例: https://zenithfall-photo-alchemy-production.up.railway.app
```

### 4. ChatGPTに登録

1. ChatGPTを開く
2. 設定 → アプリ → 「アプリを作成する」
3. 以下を入力:
   - 名前: `Zenithfall Photo Alchemy`
   - MCPサーバーのURL: `https://YOUR-RAILWAY-URL/`
   - 認証: `認証なし`
4. 「理解したうえで、続行します」にチェック
5. 「作成する」

### 5. 疎通テスト

ChatGPTで以下を試す:
```
ゲームを始めたい。種族はフェリナを選ぶ。
```

---

## MCP エンドポイント

| Method | 説明 |
|--------|------|
| `POST /` | MCP JSON-RPC メインエンドポイント |
| `GET /` | ヘルスチェック |
| `GET /health` | ヘルスチェック（Railway用） |

## 利用可能なツール

| ツール名 | 説明 |
|----------|------|
| `start_run` | ゲーム開始/再開 |
| `transmute_photo` | 写真→素材変換 |
| `craft_item` | 錬金 |
| `explore` | ダンジョン探索 |
| `gift` | ギフト贈呈 |
| `get_status` | 状態確認 |
| `get_available_dungeons` | ダンジョン一覧 |
| `get_recipes` | レシピ一覧 |

## 次のステップ

1. Railwayでデプロイ
2. ChatGPTに登録
3. 疎通テスト
4. transmute_photoのプロンプト調整
5. 本番公開
