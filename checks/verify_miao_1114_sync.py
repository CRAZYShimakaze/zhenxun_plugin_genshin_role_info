"""Verify synced rules without loading the bot or changing player data."""

import importlib
import math
import sys
import types
import unittest
from pathlib import Path

from verify_mitya_damage import profile


ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("_miao_1114_check")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
artifacts = importlib.import_module("_miao_1114_check.utils.artifact_utils")

from data_source.damage.adapter import build_context
from data_source.damage.buffs import apply_all_buffs, apply_common_buffs
from data_source.damage.calculator import DamageCalculator
from data_source.damage.engine import get_role_dmg
from data_source.damage.miao_runtime import DamageMethods
from data_source.damage.rules import get_rule


class November14SyncChecks(unittest.TestCase):
    def test_mitya_constellation_scoring(self):
        for cons in range(7):
            with self.subTest(cons=cons):
                weight, title = artifacts.get_effective(profile(cons, 0, 300))
                self.assertEqual(weight["元素充能效率"], 40 if cons else 50)
                self.assertEqual("高命" in title, cons >= 1)

    def test_truth_casket_element_moonsign_and_refinement(self):
        for element in ("火", "水", "雷", "草", "冰", "岩", "风"):
            for moonsign in (0, 1, 2):
                for refine in range(1, 6):
                    with self.subTest(element=element, moonsign=moonsign, refine=refine):
                        data = profile(0, 0, 300)
                        data["元素"] = element
                        data["武器"] = {"名称": "真语秘匣", "精炼等级": refine}
                        context = build_context(data).clone({"Moonsign": moonsign})
                        cpct = context.attr.cpct
                        notes = apply_common_buffs(context)
                        enhanced = element in ("水", "草") and moonsign >= 1
                        self.assertAlmostEqual(
                            context.attr.mastery,
                            300 + (60 + 20 * refine) * (1.5 if enhanced else 1),
                        )
                        self.assertAlmostEqual(
                            context.attr.cdmg, 100 + (27 + 9 * refine if enhanced else 0)
                        )
                        self.assertEqual(context.attr.cpct, cpct)
                        self.assertEqual(any("暴击伤害" in note for note in notes), enhanced)

    def test_valeriy_damage_shield_and_constellations(self):
        rule = get_rule("瓦列里")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.default_detail, 1)
        # Independent values from the upstream level 1 / 10 / 15 tables.
        values = {
            1: (2.292, 2.089, 1309.64, 0.2432, 0.7296),
            10: (4.1256, 3.7601, 2881.42, 0.4378, 1.3133),
            15: (5.4435, 4.9613, 4136.67, 0.5776, 1.7328),
        }
        self.assertEqual(
            [detail.title for detail in rule.details[2:]],
            ["雷元素伤害增加", "星超导反应伤害增加"],
        )
        for cons in range(7):
            for level, (charged, shield_pct, shield_flat, electro, stellar) in values.items():
                for attack in (1000, 2500):
                    with self.subTest(cons=cons, level=level, attack=attack):
                        data = profile(cons, 0, 0)
                        data["名称"] = "瓦列里"
                        data["天赋"] = [{"等级": level}] * 3
                        data["属性"]["基础攻击"] = 319.9
                        data["属性"]["额外攻击"] = attack - 319.9
                        result = get_role_dmg(data)
                        self.assertEqual(set(result), {detail.title for detail in rule.details})
                        context = build_context(data)
                        for index, detail in enumerate(rule.details):
                            active = context.clone(detail.params)
                            apply_all_buffs(active, rule.buffs)
                            calculated = detail.calculate(
                                active, DamageMethods(active, DamageCalculator(active.attr, 90, "雷"))
                            )
                            if index == 0:
                                base = attack * charged * (2 if cons == 6 else 1) * 190 / 393 * .9
                                self.assertTrue(math.isclose(calculated.avg, base * 1.5))
                                self.assertTrue(math.isclose(calculated.crit, base * 2))
                            elif index == 1:
                                self.assertTrue(math.isclose(calculated.avg, attack * shield_pct + shield_flat))
                            else:
                                multiplier = electro if index == 2 else stellar
                                self.assertTrue(math.isclose(calculated.avg, attack * multiplier))
                                self.assertIsNone(calculated.crit)
                            self.assertEqual(result[detail.title], calculated.display())

    def test_alyosha_default_detail_is_burst_healing(self):
        rule = get_rule("阿罗夏")
        self.assertEqual(rule.details[rule.default_detail].title, "Q每跳治疗量")

    def test_gilded_dreams_team_composition(self):
        for params, mastery, atk_pct in (
            ({}, 100, 14),
            ({"mArtisDiffCount": 0}, 100, 14),
            ({"mArtisDiffCount": 1}, 50, 28),
            ({"mArtisDiffCount": 2}, 100, 14),
            ({"mArtisDiffCount": 3}, 150, 0),
        ):
            with self.subTest(params=params):
                data = profile(0, 0, 300)
                data["圣遗物"] = [{"所属套装": "饰金之梦"} for _ in range(4)]
                context = build_context(data).clone(params)
                notes = apply_common_buffs(context)
                self.assertEqual(context.attr.mastery, 300 + mastery)
                self.assertEqual(context.attr.atk_pct, atk_pct)
                count = mastery // 50
                self.assertEqual(
                    notes,
                    [f"饰金之梦4：队伍存在{count:.1f}个不同元素类型角色，"
                     f"{3 - count:.1f}个相同类型角色，精通提高{mastery:.1f}，"
                     f"攻击力提高{atk_pct:.1f}%"],
                )


if __name__ == "__main__":
    unittest.main()
