"""Verify upstream formulas without importing the NoneBot plugin entry point.

Run with the bot's Python: python genshin_role_info/checks/verify_mitya_damage.py
"""

from contextlib import redirect_stdout
from io import StringIO
from math import isclose
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_source.damage.adapter import build_context
from data_source.damage.buffs import apply_all_buffs
from data_source.damage.calculator import DamageCalculator
from data_source.damage.engine import get_role_dmg
from data_source.damage.miao_runtime import DamageMethods
from data_source.damage.rules import get_rule


def profile(cons, refine, mastery):
    return {
        "名称": "米提亚", "元素": "雷", "等级": 90,
        "命座": ["命座"] * cons,
        "天赋": [{"等级": 10}] * 3,
        "武器": {"名称": "秘星典谕" if refine else "", "精炼等级": refine or 1},
        "圣遗物": [],
        "属性": {
            "基础生命": 12460.48, "额外生命": 10000,
            "基础攻击": 322.29, "额外攻击": 977.71,
            "基础防御": 847.87, "额外防御": 0,
            "伤害加成": [0] * 8, "元素精通": mastery,
            "元素充能效率": 1.4, "暴击率": 0.5,
            "暴击伤害": 1.0, "治疗加成": 0,
        },
    }


def verify_damage(cons, refine, mastery):
    data = profile(cons, refine, mastery)
    rule = get_rule("米提亚")
    assert rule is not None
    context = build_context(data)
    weapon_mastery = (120 if refine == 1 else 240) if refine else 0
    weapon_cdmg = (36 if refine == 1 else 72) if refine else 0

    # Independent inputs from upstream's level-10 tables, in display order.
    ratios = [4.032, 1.44, 1.656, None, None, 3.0, 3.0]
    steady_core = [False, True, True, True, False, True, False]
    expected_count = 7 if cons >= 4 else 5
    result = get_role_dmg(data)
    assert result is not None
    assert len(result) == expected_count + 1

    for index, detail in enumerate(rule.details[:expected_count]):
        active = context.clone(detail.params)
        notes = apply_all_buffs(active, rule.buffs)
        steady = steady_core[index]
        expected_mastery = mastery + weapon_mastery
        if steady:
            expected_mastery += 150 if cons >= 1 else 120
        if cons >= 2:
            expected_mastery += 123 if steady else 234
        assert active.attr.mastery == expected_mastery

        reaction = index not in (3, 4)
        cdmg = 100 + (40 if cons >= 1 and index in (0, 3, 4) else 0)
        if reaction:
            cdmg += weapon_cdmg
        assert active.attr.cdmg == cdmg
        assert active.attr.cpct == 70
        assert isclose(active.attr.reaction_base_pct, min(expected_mastery * 0.028, 14))
        assert active.attr.multi == (15 if cons == 6 and index in (1, 2) else 0)
        assert not any("[" in note and "]%" in note for note in notes)

        resistance = 1.05 if cons >= 2 else 0.9
        if reaction:
            base = expected_mastery * ratios[index]
            if cons == 6 and index in (1, 2):
                base *= 1.15
            noncrit = (
                base * (1 + min(expected_mastery * 0.028, 14) / 100)
                * 2 * (1 + 6 * expected_mastery / (expected_mastery + 2000))
                * (1.2 if cons == 6 else 1) * resistance
            )
        else:
            noncrit = (1300 * 6.0048 + expected_mastery * 12.0096) * 190 / 393 * resistance

        damage = detail.calculate(
            active, DamageMethods(active, DamageCalculator(active.attr, 90, "雷"))
        )
        assert isclose(damage.avg, noncrit * (1 + 0.7 * cdmg / 100))
        assert isclose(damage.crit, noncrit * (1 + cdmg / 100))
        assert result[detail.title] == damage.display()

    assert not any("稳态炉心存在" in note for note in result["额外说明"])


def verify_talent_level(level):
    data = profile(6, 5, 300)
    data["天赋"] = [{"等级": level}] * 3
    result = get_role_dmg(data)
    assert result is not None
    assert len(result) == 8
    assert all(float(values[0]) > 0 for title, values in result.items() if title != "额外说明")
    assert get_rule("瓦列里") is None


class MityaDamageTests(unittest.TestCase):
    def test_constellations_weapons_and_mastery(self):
        for cons in (0, 1, 2, 4, 6):
            for refine in (0, 1, 5):
                for mastery in (100, 1000):
                    with self.subTest(cons=cons, refine=refine, mastery=mastery):
                        output = StringIO()
                        with redirect_stdout(output):
                            verify_damage(cons, refine, mastery)
                        self.assertEqual(output.getvalue(), "")

    def test_talent_levels(self):
        for level in (1, 13, 15):
            with self.subTest(level=level):
                output = StringIO()
                with redirect_stdout(output):
                    verify_talent_level(level)
                self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
