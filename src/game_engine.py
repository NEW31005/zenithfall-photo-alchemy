"""
Zenithfall Photo Alchemy - Game Engine v2
Core logic for all tools (gift統合済み、3ターン探索、消失システム対応)
"""
from __future__ import annotations
import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from config import (
    DEBUG_MODE, JST, GameLimits, ResponseCode, make_response,
    RECIPES_PATH, DUNGEONS_PATH, RACES_PATH, MATERIALS_PATH
)


def _load_json(path) -> Any:
    """JSONファイルを読み込む"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class PlayerState:
    """プレイヤーの状態"""
    user_id: str
    
    # 相棒情報
    race_id: str = ""
    partner_name: str = ""
    phase: int = 1
    affection: float = 0.0
    
    # 進行状況
    rank: int = 1
    total_stats: int = 40  # 装備合計ステータス
    
    # インベントリ
    materials: List[Dict] = field(default_factory=list)
    items: List[Dict] = field(default_factory=list)
    catalysts: List[Dict] = field(default_factory=list)
    
    # 日次カウンター
    daily_transmute_count: int = 0
    daily_explore_count: int = 0
    daily_craft_count: int = 0  # 通常/ギフト共通プール
    last_daily_reset: str = ""  # ISO format date
    
    # 消失システム
    last_active_date: str = ""  # 最終アクティブ日（ISO format date）
    is_vanished: bool = False   # 消失状態
    has_revival_item: bool = False  # 復活アイテム所持フラグ
    
    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "race_id": self.race_id,
            "partner_name": self.partner_name,
            "phase": self.phase,
            "affection": self.affection,
            "rank": self.rank,
            "total_stats": self.total_stats,
            "materials": self.materials,
            "items": self.items,
            "catalysts": self.catalysts,
            "daily_transmute_count": self.daily_transmute_count,
            "daily_explore_count": self.daily_explore_count,
            "daily_craft_count": self.daily_craft_count,
            "last_daily_reset": self.last_daily_reset,
            "last_active_date": self.last_active_date,
            "is_vanished": self.is_vanished,
            "has_revival_item": self.has_revival_item,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PlayerState":
        # 後方互換性：古いフィールドがない場合のデフォルト
        defaults = {
            "last_active_date": "",
            "is_vanished": False,
            "has_revival_item": False,
            "daily_craft_count": data.get("daily_gift_count", 0),  # 旧gift_count移行
        }
        for key, default in defaults.items():
            if key not in data:
                data[key] = default
        # daily_gift_countは削除（craft_countに統合）
        data.pop("daily_gift_count", None)
        return cls(**data)


class GameEngine:
    """ゲームエンジン本体"""
    
    def __init__(self):
        # データ読み込み
        self.recipes_data = _load_json(RECIPES_PATH)
        self.dungeons_data = _load_json(DUNGEONS_PATH)
        self.races_data = _load_json(RACES_PATH)
        self.materials_data = _load_json(MATERIALS_PATH)
        
        # プレイヤー状態（メモリ管理）
        self._states: Dict[str, PlayerState] = {}
    
    def _get_state(self, user_id: str) -> PlayerState:
        """プレイヤー状態を取得（なければ作成）"""
        if user_id not in self._states:
            self._states[user_id] = PlayerState(user_id=user_id)
        return self._states[user_id]
    
    def _check_daily_reset(self, state: PlayerState) -> bool:
        """日次リセットをチェック・実行"""
        now = datetime.now(JST)
        today = now.strftime("%Y-%m-%d")
        
        if state.last_daily_reset != today:
            # リセット実行
            state.daily_transmute_count = 0
            state.daily_explore_count = 0
            state.daily_craft_count = 0
            state.last_daily_reset = today
            return True
        return False
    
    def _update_active_date(self, state: PlayerState) -> None:
        """最終アクティブ日を更新"""
        today = datetime.now(JST).strftime("%Y-%m-%d")
        state.last_active_date = today
    
    def _check_vanish_status(self, state: PlayerState) -> Dict:
        """消失状態をチェック・更新"""
        if not state.race_id:
            # まだ相棒がいない
            return {"changed": False, "is_vanished": False}
        
        if not state.last_active_date:
            # 初回：アクティブ日を設定
            self._update_active_date(state)
            return {"changed": False, "is_vanished": False}
        
        today = datetime.now(JST).date()
        last_active = datetime.strptime(state.last_active_date, "%Y-%m-%d").date()
        days_inactive = (today - last_active).days
        
        was_vanished = state.is_vanished
        
        if days_inactive >= GameLimits.VANISH_DAYS and not state.is_vanished:
            # 消失発生
            state.is_vanished = True
            state.has_revival_item = False  # 復活アイテムリセット
            return {
                "changed": True, 
                "is_vanished": True,
                "days_inactive": days_inactive,
                "message": f"……{state.partner_name}の姿が見えない。{days_inactive}日間会いに来なかったから、存在が薄れてしまった。"
            }
        
        return {"changed": False, "is_vanished": state.is_vanished}
    
    def _try_revival(self, state: PlayerState) -> Dict:
        """消失状態からの復活を試みる（復活アイテムがあれば）"""
        if not state.is_vanished:
            return {"revived": False}
        
        if state.has_revival_item:
            state.is_vanished = False
            state.has_revival_item = False
            self._update_active_date(state)
            return {
                "revived": True,
                "message": f"「……もっと会いに来て。怖い思いした」{state.partner_name}の輪郭が戻ってきた。"
            }
        
        return {"revived": False}
    
    def _grant_revival_item(self, state: PlayerState) -> bool:
        """消失中なら復活アイテムを確定付与"""
        if state.is_vanished and not state.has_revival_item:
            state.has_revival_item = True
            return True
        return False
    
    def _get_race_data(self, race_id: str) -> Dict:
        """種族データを取得"""
        return self.races_data.get("races", {}).get(race_id, {})
    
    def _get_catalyst_by_id(self, catalyst_id: str) -> Optional[Dict]:
        """触媒マスタからIDで検索"""
        catalysts = self.recipes_data.get("catalysts", {})
        for rank_key, cat_list in catalysts.items():
            for cat in cat_list:
                if cat.get("catalyst_id") == catalyst_id:
                    return cat
        return None
    
    def _calculate_phase(self, affection: float) -> int:
        """好感度からPhaseを計算"""
        thresholds = [0, 20, 40, 60, 80]  # Phase 1-5
        for i, threshold in enumerate(thresholds):
            if affection < threshold:
                return i
        return 5
    
    def _check_rank_up(self, state: PlayerState) -> Dict:
        """ランクアップ判定"""
        rank_reqs = self.dungeons_data.get("rank_requirements", {})
        current_rank = state.rank
        
        for rank_str in ["2", "3", "4", "5"]:
            rank_num = int(rank_str)
            if rank_num <= current_rank:
                continue
            req = rank_reqs.get(rank_str, {})
            min_stats = req.get("min_total_stats", 999)
            if state.total_stats >= min_stats:
                state.rank = rank_num
                return {
                    "ranked_up": True,
                    "new_rank": rank_num,
                    "rank_name": req.get("name", f"Rank{rank_num}")
                }
        
        return {"ranked_up": False}
    
    # ========================================
    # Tool 1: start_run
    # ========================================
    def start_run(self, user_id: str, payload: Dict) -> Dict:
        """
        ゲーム開始・再開
        
        payload:
          - race_id: str (種族ID、新規時必須)
          - partner_name: str (相棒名、省略可)
          - force_new: bool (強制新規)
        """
        state = self._get_state(user_id)
        self._check_daily_reset(state)
        
        force_new = payload.get("force_new", False)
        
        # 既存データありの場合
        if state.race_id and not force_new:
            # 消失チェック
            vanish_result = self._check_vanish_status(state)
            self._update_active_date(state)
            
            return make_response(
                ok=True,
                code=ResponseCode.OK,
                state_patch=state.to_dict(),
                ui_hints={
                    "is_new_game": False,
                    "vanish_status": vanish_result,
                },
                message=f"おかえり。{state.partner_name}が待っていたよ。" if not state.is_vanished else vanish_result.get("message", "")
            )
        
        # 新規ゲーム
        race_id = payload.get("race_id", "")
        if not race_id:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message="種族を選択してください（hume/sylva/felina/tigr/lupus）"
            )
        
        race_data = self._get_race_data(race_id)
        if not race_data:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message=f"不明な種族: {race_id}"
            )
        
        partner_name = payload.get("partner_name", race_data.get("default_name_ja", "相棒"))
        
        # 初期化
        state.race_id = race_id
        state.partner_name = partner_name
        state.phase = 1
        state.affection = 0.0
        state.rank = 1
        state.total_stats = race_data.get("base_stats_total", 40)
        state.materials = []
        state.items = []
        state.catalysts = []
        state.is_vanished = False
        state.has_revival_item = False
        self._update_active_date(state)
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            state_patch=state.to_dict(),
            ui_hints={
                "is_new_game": True,
                "race_info": {
                    "name_ja": race_data.get("name_ja"),
                    "description": race_data.get("description"),
                }
            },
            message=f"{partner_name}が召喚された。一緒にゼニスフォールを救おう。"
        )
    
    # ========================================
    # Tool 2: transmute_photo
    # ========================================
    def transmute_photo(self, user_id: str, payload: Dict) -> Dict:
        """
        写真転生
        
        payload:
          - detected_material: str (材質)
          - detected_essence: str (概念)
          - detected_quality: int (品質1-5)
          - hint_text: str (説明)
        """
        state = self._get_state(user_id)
        self._check_daily_reset(state)
        self._update_active_date(state)
        
        # 制限チェック
        limit = GameLimits.get_limit("DAILY_TRANSMUTE_LIMIT")
        if state.daily_transmute_count >= limit:
            return make_response(
                ok=False,
                code=ResponseCode.LIMIT_REACHED,
                message=f"今日の写真転生回数上限（{limit}回）に達しました"
            )
        
        material = payload.get("detected_material", "")
        essence = payload.get("detected_essence", "")
        quality = payload.get("detected_quality", 2)
        hint = payload.get("hint_text", "")
        
        # バリデーション
        materials_dict = self.materials_data.get("materials", {})
        essences_dict = self.materials_data.get("essences", {})
        valid_materials = list(materials_dict.keys())
        valid_essences = list(essences_dict.keys())
        
        if material not in valid_materials:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message=f"不明な材質: {material}"
            )
        if essence not in valid_essences:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message=f"不明な概念: {essence}"
            )
        
        quality = max(1, min(5, quality))
        
        # 素材生成
        material_id = f"mat_{uuid.uuid4().hex[:8]}"
        material_data = materials_dict.get(material, {})
        essence_data = essences_dict.get(essence, {})
        quality_dict = self.materials_data.get("quality", {})
        quality_data = quality_dict.get(str(quality), {})
        
        new_material = {
            "material_id": material_id,
            "material_type": material,
            "material_name_ja": material_data.get("name_ja", material),
            "essence": essence,
            "essence_name_ja": essence_data.get("name_ja", essence),
            "quality": quality,
            "quality_name_ja": quality_data.get("name_ja", "並"),
            "hint": hint,
            "created_at": datetime.now(JST).isoformat(),
        }
        
        state.materials.append(new_material)
        state.daily_transmute_count += 1
        
        # 消失中なら復活アイテム確定付与
        revival_granted = self._grant_revival_item(state)
        revival_result = None
        if revival_granted:
            revival_result = self._try_revival(state)
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            state_patch={
                "materials": state.materials,
                "daily_transmute_count": state.daily_transmute_count,
                "is_vanished": state.is_vanished,
                "has_revival_item": state.has_revival_item,
            },
            ui_hints={
                "new_material": new_material,
                "revival": revival_result,
            },
            log={
                "action": "transmute_photo",
                "material": material,
                "essence": essence,
                "quality": quality,
            },
            message=f"「{material_data.get('name_ja', material)}」の素材を手に入れた！（{quality_data.get('name_ja', '並')}）"
        )
    
    # ========================================
    # Tool 3: craft_item（通常/ギフト統合）
    # ========================================
    def craft_item(self, user_id: str, payload: Dict) -> Dict:
        """
        錬金（生成） - 通常生成とギフト生成を統合
        
        payload:
          - material_ids: List[str] (素材ID配列)
          - catalyst_id: str (触媒ID、省略可)
          - craft_type: str ("normal" or "gift")
        """
        state = self._get_state(user_id)
        self._check_daily_reset(state)
        self._update_active_date(state)
        
        # 消失中は錬金可能（復活アイテム付与のため）
        
        # 制限チェック（通常/ギフト共通プール）
        limit = GameLimits.get_limit("DAILY_CRAFT_LIMIT")
        if state.daily_craft_count >= limit:
            return make_response(
                ok=False,
                code=ResponseCode.LIMIT_REACHED,
                message=f"今日の錬金回数上限（{limit}回）に達しました"
            )
        
        material_ids = payload.get("material_ids", [])
        catalyst_id = payload.get("catalyst_id")
        craft_type = payload.get("craft_type", "normal")
        
        if not material_ids:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message="素材を選択してください"
            )
        
        # 素材検索
        used_materials = []
        for mid in material_ids:
            mat = next((m for m in state.materials if m["material_id"] == mid), None)
            if not mat:
                return make_response(
                    ok=False,
                    code=ResponseCode.HARD_FAIL,
                    message=f"素材が見つかりません: {mid}"
                )
            used_materials.append(mat)
        
        # 触媒検索（任意）
        used_catalyst = None
        if catalyst_id:
            cat = next((c for c in state.catalysts if c["catalyst_id"] == catalyst_id), None)
            if not cat:
                return make_response(
                    ok=False,
                    code=ResponseCode.HARD_FAIL,
                    message=f"触媒が見つかりません: {catalyst_id}"
                )
            used_catalyst = cat
        
        # レシピマッチング
        if craft_type == "gift":
            result = self._craft_gift(state, used_materials, used_catalyst)
        else:
            result = self._craft_normal(state, used_materials, used_catalyst)
        
        # 素材消費
        for mat in used_materials:
            state.materials.remove(mat)
        
        # 触媒消費
        if used_catalyst:
            state.catalysts.remove(used_catalyst)
        
        state.daily_craft_count += 1
        
        # 消失中なら復活アイテム確定付与
        revival_granted = self._grant_revival_item(state)
        revival_result = None
        if revival_granted:
            revival_result = self._try_revival(state)
        
        return make_response(
            ok=result["ok"],
            code=result["code"],
            state_patch={
                "materials": state.materials,
                "catalysts": state.catalysts,
                "items": state.items,
                "daily_craft_count": state.daily_craft_count,
                "affection": state.affection,
                "phase": state.phase,
                "is_vanished": state.is_vanished,
                "has_revival_item": state.has_revival_item,
            },
            ui_hints={
                "craft_type": craft_type,
                "crafted_item": result.get("item"),
                "reaction": result.get("reaction"),
                "phase_up": result.get("phase_up", False),
                "revival": revival_result,
            },
            log={
                "action": "craft_item",
                "craft_type": craft_type,
                "materials_used": [m["material_id"] for m in used_materials],
                "catalyst_used": catalyst_id,
                "result": result.get("item"),
            },
            message=result.get("message", "")
        )
    
    def _craft_normal(self, state: PlayerState, materials: List[Dict], catalyst: Optional[Dict]) -> Dict:
        """通常生成のマッチング"""
        # 素材の属性を集める
        mat_types = set(m["material_type"] for m in materials)
        essences = set(m["essence"] for m in materials)
        avg_quality = sum(m["quality"] for m in materials) / len(materials)
        
        # 触媒の属性も追加
        if catalyst:
            mat_types.add(catalyst.get("material", ""))
            essences.add(catalyst.get("essence", ""))
        
        # レシピマッチング
        recipes = self.recipes_data.get("recipes", [])
        matched_recipe = None
        
        for recipe in recipes:
            req = recipe.get("required_attributes", {})
            req_materials = set(req.get("materials", []))
            req_essences = set(req.get("essences", []))
            
            # 必須属性がすべて含まれているか
            if req_materials.issubset(mat_types) and req_essences.issubset(essences):
                # ランクチェック
                if recipe.get("rank", 1) <= state.rank:
                    matched_recipe = recipe
                    break
        
        if matched_recipe:
            # 成功
            item_id = f"item_{uuid.uuid4().hex[:8]}"
            new_item = {
                "item_id": item_id,
                "recipe_id": matched_recipe.get("id"),
                "name_ja": matched_recipe.get("name_ja"),
                "name_en": matched_recipe.get("name_en"),
                "category": matched_recipe.get("category", "equipment"),
                "quality": round(avg_quality),
                "stats": matched_recipe.get("stats", {}),
                "created_at": datetime.now(JST).isoformat(),
            }
            state.items.append(new_item)
            
            return {
                "ok": True,
                "code": ResponseCode.OK,
                "item": new_item,
                "message": f"「{new_item['name_ja']}」を錬成した！"
            }
        else:
            # 失敗 → ガラクタ
            junks = self.recipes_data.get("junk_items", [])
            junk = random.choice(junks) if junks else {"id": "junk_unknown", "name_ja": "謎のガラクタ"}
            
            item_id = f"junk_{uuid.uuid4().hex[:8]}"
            new_item = {
                "item_id": item_id,
                "recipe_id": junk.get("id"),
                "name_ja": junk.get("name_ja", "ガラクタ"),
                "name_en": junk.get("name_en", "Junk"),
                "category": "junk",
                "quality": 1,
                "stats": {},
                "created_at": datetime.now(JST).isoformat(),
            }
            state.items.append(new_item)
            
            return {
                "ok": True,
                "code": ResponseCode.SOFT_FAIL,
                "item": new_item,
                "message": f"錬金失敗……「{new_item['name_ja']}」ができた。"
            }
    
    def _craft_gift(self, state: PlayerState, materials: List[Dict], catalyst: Optional[Dict]) -> Dict:
        """ギフト生成 → 即時贈呈"""
        # ギフトレシピマッチング
        gift_recipes = self.recipes_data.get("gift_recipes", [])
        
        mat_types = set(m["material_type"] for m in materials)
        essences = set(m["essence"] for m in materials)
        avg_quality = sum(m["quality"] for m in materials) / len(materials)
        
        matched_gift = None
        for gift in gift_recipes:
            req = gift.get("required_attributes", {})
            req_essences = set(req.get("essences", []))
            if req_essences.issubset(essences):
                matched_gift = gift
                break
        
        if not matched_gift:
            # デフォルトギフト
            matched_gift = {
                "id": "gift_generic",
                "name_ja": "手作りの贈り物",
                "base_affection": 2.0
            }
        
        # 好感度計算
        race_data = self._get_race_data(state.race_id)
        preferences = race_data.get("preferences", {})
        like_essences = preferences.get("like_essences", [])
        dislike_essences = preferences.get("dislike_essences", [])
        
        base_affection = matched_gift.get("base_affection", 3.0)
        bonus = 0.0
        
        for ess in essences:
            if ess in like_essences:
                bonus += 2.0
            elif ess in dislike_essences:
                bonus -= 1.0
        
        # 品質ボーナス
        quality_bonus = (avg_quality - 3) * 0.5
        
        total_affection = max(0.5, base_affection + bonus + quality_bonus)
        
        # 好感度適用
        state.affection = min(state.affection + total_affection, GameLimits.AFFECTION_MAX)
        
        # Phase進行チェック
        new_phase = self._calculate_phase(state.affection)
        phase_up = new_phase > state.phase
        if phase_up:
            state.phase = new_phase
        
        # 反応生成
        is_liked = bonus > 0
        reaction = self._generate_gift_reaction(race_data, is_liked)
        
        return {
            "ok": True,
            "code": ResponseCode.OK,
            "item": {
                "name_ja": matched_gift.get("name_ja"),
                "affection_gain": total_affection,
            },
            "reaction": reaction,
            "phase_up": phase_up,
            "message": f"「{matched_gift.get('name_ja')}」を{state.partner_name}に贈った。{reaction}"
        }
    
    def _generate_gift_reaction(self, race_data: Dict, is_liked: bool) -> str:
        """ギフト反応を生成"""
        gift_reactions = race_data.get("gift_reactions", {})
        
        if is_liked:
            reactions = gift_reactions.get("like", ["ありがとう！すごく嬉しい"])
        else:
            reactions = gift_reactions.get("dislike", ["……ありがとう"])
        
        return random.choice(reactions) if reactions else "……"
    
    # ========================================
    # Tool 4: explore（3ターン制）
    # ========================================
    def explore(self, user_id: str, payload: Dict) -> Dict:
        """
        ダンジョン探索（3ターン制）
        
        Turn1/Turn2: 通常敵ランダム遭遇あり → 主素材×1（敵遭遇時：+副素材×1）
        Turn3: ボス戦（固定）→ 主素材×2 + 副素材×1
        宝箱: 2〜4素材（60%:2個 / 30%:3個 / 10%:4個）
        
        payload:
          - dungeon_id: str (ダンジョンID)
          - style: str (heal/guard/none)
        """
        state = self._get_state(user_id)
        self._check_daily_reset(state)
        self._update_active_date(state)
        
        # 消失中は探索不可
        if state.is_vanished:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message=f"{state.partner_name}の姿が見えない……探索はできない。まず存在を取り戻して。"
            )
        
        # 制限チェック
        limit = GameLimits.get_limit("DAILY_EXPLORE_LIMIT")
        if state.daily_explore_count >= limit:
            return make_response(
                ok=False,
                code=ResponseCode.LIMIT_REACHED,
                message=f"今日の探索回数上限（{limit}回）に達しました"
            )
        
        dungeon_id = payload.get("dungeon_id", "")
        style = payload.get("style", "none")
        
        # ダンジョン検索
        dungeon = self._find_dungeon(dungeon_id)
        if not dungeon:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message=f"ダンジョンが見つかりません: {dungeon_id}"
            )
        
        # ランクチェック
        dungeon_rank = dungeon.get("rank", 1)
        if dungeon_rank > state.rank:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message=f"ランク{dungeon_rank}以上が必要です（現在: {state.rank}）"
            )
        
        # 成功率計算
        base_rate = dungeon.get("base_success_rate", 0.7)
        modifiers = self.dungeons_data.get("exploration_rules", {}).get("success_rate_modifiers", {})
        
        final_rate = base_rate
        if style == "heal":
            final_rate += modifiers.get("support_heal", 0.05)
        elif style == "guard":
            final_rate += modifiers.get("support_guard", 0.10)
        
        # 装備ボーナス
        equip_bonus = modifiers.get("equipment_bonus", {})
        per_stat = equip_bonus.get("per_stat_point", 0.005)
        cap = equip_bonus.get("cap", 0.20)
        stat_bonus = min((state.total_stats - 40) * per_stat, cap)
        final_rate += stat_bonus
        
        # 3ターン探索実行
        exploration_log = []
        all_drops = []
        success = True
        
        for turn in range(1, 4):
            turn_result = self._execute_explore_turn(
                turn, dungeon, state, final_rate
            )
            exploration_log.append(turn_result)
            
            if turn_result.get("drops"):
                all_drops.extend(turn_result["drops"])
            
            if not turn_result.get("survived", True):
                success = False
                break
        
        # 生存した場合：宝箱
        treasure_drops = []
        if success:
            treasure_drops = self._generate_treasure(dungeon, state)
            all_drops.extend(treasure_drops)
        
        # ドロップを触媒リストに追加
        for drop in all_drops:
            state.catalysts.append(drop)
        
        state.daily_explore_count += 1
        
        # 好感度上昇（成功時）
        phase_up = False
        if success:
            state.affection = min(state.affection + 1.0, GameLimits.AFFECTION_MAX)
            new_phase = self._calculate_phase(state.affection)
            phase_up = new_phase > state.phase
            if phase_up:
                state.phase = new_phase
        
        return make_response(
            ok=True,
            code=ResponseCode.OK if success else ResponseCode.SOFT_FAIL,
            state_patch={
                "catalysts": state.catalysts,
                "affection": state.affection,
                "phase": state.phase,
                "daily_explore_count": state.daily_explore_count,
            },
            ui_hints={
                "result": "success" if success else "failure",
                "phase_up": phase_up,
                "exploration_log": exploration_log,
                "treasure_count": len(treasure_drops),
                "total_drops": len(all_drops),
                "suggest_next": self._generate_next_suggestion(state) if success else None,
            },
            log={
                "action": "explore",
                "dungeon_id": dungeon_id,
                "style": style,
                "success": success,
                "turns_completed": len(exploration_log),
                "drops": [d["catalyst_id"] for d in all_drops],
            },
            message=self._generate_explore_message(success, all_drops, state)
        )
    
    def _execute_explore_turn(self, turn: int, dungeon: Dict, state: PlayerState, success_rate: float) -> Dict:
        """各ターンの探索を実行"""
        result = {
            "turn": turn,
            "drops": [],
            "survived": True,
            "enemy_encountered": False,
            "is_boss": turn == 3,
        }
        
        # Turn3はボス戦（固定）、Turn1/2は通常敵ランダム
        if turn == 3:
            # ボス戦
            result["enemy_encountered"] = True
            roll = random.random()
            if roll >= success_rate:
                result["survived"] = False
                result["message"] = "ボス戦で敗北……撤退を余儀なくされた。"
                return result
            
            # ボス勝利：主素材×2 + 副素材×1
            for _ in range(2):
                drop = self._generate_dungeon_drop(dungeon, state, is_primary=True)
                if drop:
                    result["drops"].append(drop)
            
            secondary = self._generate_dungeon_drop(dungeon, state, is_primary=False)
            if secondary:
                result["drops"].append(secondary)
            
            result["message"] = "ボスを撃破！"
        else:
            # 通常ターン（敵遭遇50%）
            enemy_roll = random.random()
            if enemy_roll < 0.5:
                result["enemy_encountered"] = True
                battle_roll = random.random()
                if battle_roll >= success_rate + 0.1:  # 通常敵は少し楽
                    result["survived"] = False
                    result["message"] = f"Turn{turn}で敵に敗北……撤退。"
                    return result
                
                # 敵撃破：主素材×1 + 副素材×1
                primary = self._generate_dungeon_drop(dungeon, state, is_primary=True)
                if primary:
                    result["drops"].append(primary)
                secondary = self._generate_dungeon_drop(dungeon, state, is_primary=False)
                if secondary:
                    result["drops"].append(secondary)
                
                result["message"] = f"Turn{turn}: 敵を撃破！"
            else:
                # 敵なし：主素材×1
                primary = self._generate_dungeon_drop(dungeon, state, is_primary=True)
                if primary:
                    result["drops"].append(primary)
                result["message"] = f"Turn{turn}: 順調に進行中……"
        
        return result
    
    def _generate_treasure(self, dungeon: Dict, state: PlayerState) -> List[Dict]:
        """宝箱ドロップを生成（2〜4素材）"""
        probs = GameLimits.TREASURE_PROBS  # [0.60, 0.30, 0.10]
        roll = random.random()
        
        if roll < probs[0]:
            count = 2
        elif roll < probs[0] + probs[1]:
            count = 3
        else:
            count = 4
        
        drops = []
        for _ in range(count):
            drop = self._generate_dungeon_drop(dungeon, state, is_primary=random.choice([True, False]))
            if drop:
                drops.append(drop)
        
        return drops
    
    def _find_dungeon(self, dungeon_id: str) -> Optional[Dict]:
        """ダンジョンを検索"""
        dungeons = self.dungeons_data.get("dungeons", {})
        for rank_key, dungeon_list in dungeons.items():
            for d in dungeon_list:
                if d.get("id") == dungeon_id:
                    return d
        return None
    
    def _generate_dungeon_drop(self, dungeon: Dict, state: PlayerState, is_primary: bool = True) -> Optional[Dict]:
        """ダンジョンドロップを生成"""
        drop_table = dungeon.get("catalyst_drop_table", [])
        if not drop_table:
            return None
        
        # 重み付き抽選
        total_weight = sum(d.get("weight", 1) for d in drop_table)
        roll = random.random() * total_weight
        
        cumulative = 0
        selected_id = None
        for entry in drop_table:
            cumulative += entry.get("weight", 1)
            if roll < cumulative:
                selected_id = entry.get("catalyst_id")
                break
        
        if not selected_id:
            return None
        
        # 触媒マスタから取得
        catalyst = self._get_catalyst_by_id(selected_id)
        if not catalyst:
            return None
        
        return {
            "catalyst_id": f"{selected_id}_{uuid.uuid4().hex[:6]}",  # ユニークID
            "base_catalyst_id": selected_id,
            "name_ja": catalyst.get("name_ja", "不明な触媒"),
            "name_en": catalyst.get("name_en", "Unknown Catalyst"),
            "material": catalyst.get("material", ""),
            "essence": catalyst.get("essence", ""),
            "is_primary": is_primary,
            "obtained_at": datetime.now(JST).isoformat(),
        }
    
    def _generate_explore_message(self, success: bool, drops: List[Dict], state: PlayerState) -> str:
        """探索結果メッセージを生成"""
        if not success:
            return "探索失敗……無事に戻れただけでも幸運だ。"
        
        if not drops:
            return "探索成功！でも何も見つからなかった……"
        
        drop_names = [d["name_ja"] for d in drops[:3]]
        if len(drops) > 3:
            return f"探索成功！「{', '.join(drop_names)}」など{len(drops)}個の触媒を手に入れた！"
        else:
            return f"探索成功！「{', '.join(drop_names)}」を手に入れた！"
    
    def _generate_next_suggestion(self, state: PlayerState) -> Dict:
        """次の行動提案"""
        race_data = self._get_race_data(state.race_id)
        preferences = race_data.get("preferences", {})
        like_essences = preferences.get("like_essences", [])
        
        suggested = random.choice(like_essences) if like_essences else "control"
        
        return {
            "action": "transmute_photo",
            "reason": f"「{suggested}」っぽい写真を撮ってきて。",
            "essence_hint": suggested,
        }
    
    # ========================================
    # Tool 5: get_status
    # ========================================
    def get_status(self, user_id: str, payload: Dict) -> Dict:
        """現在の状態を取得"""
        state = self._get_state(user_id)
        self._check_daily_reset(state)
        
        # 消失チェック（状態確認時にも）
        vanish_result = self._check_vanish_status(state)
        
        race_data = self._get_race_data(state.race_id) if state.race_id else {}
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            state_patch=state.to_dict(),
            ui_hints={
                "race_info": race_data,
                "vanish_status": vanish_result,
                "limits": {
                    "transmute": f"{state.daily_transmute_count}/{GameLimits.get_limit('DAILY_TRANSMUTE_LIMIT')}",
                    "craft": f"{state.daily_craft_count}/{GameLimits.get_limit('DAILY_CRAFT_LIMIT')}",
                    "explore": f"{state.daily_explore_count}/{GameLimits.get_limit('DAILY_EXPLORE_LIMIT')}",
                }
            }
        )
    
    # ========================================
    # Tool 6: get_available_dungeons
    # ========================================
    def get_available_dungeons(self, user_id: str, payload: Dict) -> Dict:
        """利用可能なダンジョン一覧"""
        state = self._get_state(user_id)
        
        available = []
        dungeons = self.dungeons_data.get("dungeons", {})
        
        for rank_key, dungeon_list in dungeons.items():
            for d in dungeon_list:
                if d.get("rank", 1) <= state.rank:
                    available.append({
                        "id": d.get("id"),
                        "name_ja": d.get("name_ja"),
                        "name_en": d.get("name_en"),
                        "rank": d.get("rank"),
                        "difficulty": d.get("difficulty"),
                        "base_success_rate": d.get("base_success_rate"),
                        "description": d.get("description"),
                    })
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            ui_hints={
                "dungeons": available,
                "current_rank": state.rank,
            }
        )
    
    # ========================================
    # Tool 7: get_recipes
    # ========================================
    def get_recipes(self, user_id: str, payload: Dict) -> Dict:
        """利用可能なレシピ一覧"""
        state = self._get_state(user_id)
        
        available = []
        recipes = self.recipes_data.get("recipes", [])
        
        for r in recipes:
            if r.get("rank", 1) <= state.rank:
                available.append({
                    "id": r.get("id"),
                    "name_ja": r.get("name_ja"),
                    "name_en": r.get("name_en"),
                    "category": r.get("category"),
                    "rank": r.get("rank"),
                    "required_attributes": r.get("required_attributes"),
                    "description": r.get("description"),
                })
        
        # ギフトレシピも追加
        gift_recipes = self.recipes_data.get("gift_recipes", [])
        for g in gift_recipes:
            available.append({
                "id": g.get("id"),
                "name_ja": g.get("name_ja"),
                "category": "gift",
                "required_attributes": g.get("required_attributes"),
            })
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            ui_hints={
                "recipes": available,
                "current_rank": state.rank,
            }
        )
    
    # ========================================
    # デバッグ用
    # ========================================
    def debug_reset_daily(self, user_id: str) -> Dict:
        """デバッグ用：日次カウンターをリセット"""
        if not DEBUG_MODE:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message="デバッグモードではありません"
            )
        
        state = self._get_state(user_id)
        state.daily_transmute_count = 0
        state.daily_explore_count = 0
        state.daily_craft_count = 0
        state.last_daily_reset = ""
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            message="日次カウンターをリセットしました",
            state_patch=state.to_dict()
        )
    
    def debug_set_state(self, user_id: str, payload: Dict) -> Dict:
        """デバッグ用：状態を直接設定"""
        if not DEBUG_MODE:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message="デバッグモードではありません"
            )
        
        state = self._get_state(user_id)
        
        # 許可されたフィールドのみ更新
        allowed = ["phase", "affection", "rank", "total_stats", "is_vanished", "has_revival_item"]
        for key in allowed:
            if key in payload:
                setattr(state, key, payload[key])
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            message="状態を更新しました",
            state_patch=state.to_dict()
        )
    
    def debug_force_vanish(self, user_id: str) -> Dict:
        """デバッグ用：強制消失"""
        if not DEBUG_MODE:
            return make_response(
                ok=False,
                code=ResponseCode.HARD_FAIL,
                message="デバッグモードではありません"
            )
        
        state = self._get_state(user_id)
        state.is_vanished = True
        state.has_revival_item = False
        
        return make_response(
            ok=True,
            code=ResponseCode.OK,
            message="相棒を消失状態にしました",
            state_patch=state.to_dict()
        )


# シングルトンインスタンス
_engine: Optional[GameEngine] = None

def get_engine() -> GameEngine:
    global _engine
    if _engine is None:
        _engine = GameEngine()
    return _engine
