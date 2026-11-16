"""Run with the bot's Python, without loading NoneBot or writing player data."""

import importlib
from pathlib import Path
import sys
import types
import unittest

from verify_mitya_damage import profile


ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("_miao_sync_check")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
cards = importlib.import_module("_miao_sync_check.utils.card_utils")
artifacts = importlib.import_module("_miao_sync_check.utils.artifact_utils")

from data_source.damage.adapter import build_context
from data_source.damage.buffs import apply_common_buffs


class NovemberSyncChecks(unittest.TestCase):
    def test_static_weapon_bonuses_are_not_applied_twice(self):
        for refine in range(1, 6):
            with self.subTest(weapon="漩流颂歌", refine=refine):
                data = profile(0, 0, 300)
                data["武器"] = {"名称": "漩流颂歌", "精炼等级": refine}
                # The API's panel already contains the static healing bonus.
                data["属性"]["治疗加成"] = (refine + 3) / 100
                context = build_context(data)
                hp = context.attr.hp
                notes = apply_common_buffs(context)
                self.assertAlmostEqual(context.attr.heal, refine + 3)
                self.assertAlmostEqual(
                    context.attr.hp - hp,
                    context.attr.base_hp * (refine + 3) * 5.25 / 100,
                )
                self.assertFalse(any("治疗加成提升" in note for note in notes))
            with self.subTest(weapon="「究极霸王超级魔剑」", refine=refine):
                data["武器"]["名称"] = "「究极霸王超级魔剑」"
                context = build_context(data)
                attack = context.attr.atk
                apply_common_buffs(context)
                self.assertAlmostEqual(
                    context.attr.atk - attack,
                    context.attr.base_atk * (refine + 3) * 3 / 100,
                )

    def test_odetta_recharge_weight_starts_at_four_constellations(self):
        for cons in range(7):
            with self.subTest(cons=cons):
                data = profile(cons, 0, 300)
                data["名称"] = "奥黛塔"
                weight, name = artifacts.get_effective(data)
                self.assertEqual(weight["元素充能效率"], 50 if cons >= 4 else 20)
                self.assertEqual("高命" in name, cons >= 4)

    def test_mitya_api_mastery_and_burst_id_are_preserved(self):
        props = {str(key): 0 for key in (1, 4, 7, 20, 22, 23, 26, 27, 28, 30, 2000, 2001, 2002, *range(40, 47))}
        props["28"] = 400  # Includes the character's permanent 100 EM.
        player = cards.PlayerInfo.__new__(cards.PlayerInfo)
        player.roles = {}
        player.set_role({
            "avatarId": 10000136,
            "propMap": {"4001": {"val": "90"}},
            "skillLevelMap": {"11361": 6, "11362": 8, "11364": 10},
            "fightPropMap": props,
            "equipList": [{
                "weapon": {"level": 90},
                "flat": {
                    "nameTextMapHash": "4206156163",
                    "icon": "UI_EquipIcon_Catalyst_PermansorTerrae",
                    "rankLevel": 5,
                    "weaponStats": [{"statValue": 500}],
                },
            }],
        })
        role = player.roles["米提亚"]
        self.assertEqual(role["属性"]["元素精通"], 400)
        self.assertEqual([talent["等级"] for talent in role["天赋"]], [6, 8, 10])
        self.assertEqual(role["天赋"][2]["图标"], "Skill_E_Mitya_01")
        self.assertEqual(build_context(role).attr.mastery, 400)


if __name__ == "__main__":
    unittest.main()
