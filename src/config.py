"""
Zenithfall Photo Alchemy - Configuration
"""
import os
from pathlib import Path
from datetime import timezone, timedelta

# ========================================
# デバッグモード
# ========================================
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ========================================
# パス設定
# ========================================
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("ZENITHFALL_DATA_DIR", BASE_DIR / "data"))

RECIPES_PATH = DATA_DIR / "recipes_v1_0.json"
DUNGEONS_PATH = DATA_DIR / "dungeons_v1_3.json"
RACES_PATH = DATA_DIR / "races_v1_2.json"
MATERIALS_PATH = DATA_DIR / "materials_schema.json"

# ========================================
# タイムゾーン（JST固定）
# ========================================
JST = timezone(timedelta(hours=9))

# ========================================
# ゲーム制限（通常モード）
# ========================================
class GameLimits:
    # 1日の制限（v1.0 仕様確定）
    DAILY_TRANSMUTE_LIMIT = 3      # 写真転生回数
    DAILY_EXPLORE_LIMIT = 1        # ダンジョン攻略回数
    DAILY_CRAFT_LIMIT = 3          # 錬金（生成）回数 ※通常/ギフト共通プール
    # ※ギフトは別枠ではなく、錬金（生成）の中で選択する方式
    
    # インベントリ制限
    MAX_MATERIALS = 50             # 素材所持上限
    MAX_ITEMS = 30                 # アイテム所持上限
    MAX_CATALYSTS = 20             # 触媒所持上限
    
    # 好感度
    AFFECTION_MAX = 100            # 好感度上限
    AFFECTION_PER_PHASE = 20       # Phase進行に必要な好感度
    
    # 消失システム
    VANISH_DAYS = 30               # 消失までの日数
    
    # 探索システム
    EXPLORE_TURNS = 3              # 探索のターン数
    TREASURE_PROBS = [0.60, 0.30, 0.10]  # 宝箱確率（2個/3個/4個）
    
    @classmethod
    def get_limit(cls, key: str) -> int:
        """デバッグモードなら制限を大幅緩和"""
        if DEBUG_MODE:
            # デバッグ時は実質無制限
            if key.startswith("DAILY_"):
                return 9999
            if key.startswith("MAX_"):
                return 9999
        return getattr(cls, key, 0)

# ========================================
# レスポンスコード
# ========================================
class ResponseCode:
    OK = "OK"
    SOFT_FAIL = "SOFT_FAIL"      # ゲーム的失敗（ガラクタ生成など）
    HARD_FAIL = "HARD_FAIL"      # システムエラー
    LIMIT_REACHED = "LIMIT_REACHED"  # 制限到達

# ========================================
# 統一レスポンス生成
# ========================================
def make_response(
    ok: bool = True,
    code: str = ResponseCode.OK,
    state_patch: dict = None,
    ui_hints: dict = None,
    log: dict = None,
    message: str = None
) -> dict:
    """統一フォーマットでレスポンスを生成"""
    return {
        "ok": ok,
        "code": code,
        "state_patch": state_patch or {},
        "ui_hints": ui_hints or {},
        "log": log or {},
        "message": message
    }
