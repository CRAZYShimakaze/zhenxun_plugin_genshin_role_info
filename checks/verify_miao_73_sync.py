"""Check 7.3 API conversion, constellation levels and bundled panel resources."""

import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
package = types.ModuleType("_miao_73_check")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
cards = importlib.import_module("_miao_73_check.utils.card_utils")
artifacts = importlib.import_module("_miao_73_check.utils.artifact_utils")


def make_role(name, cons):
    metadata = cards.role_info_json[name]
    props = {str(key): 0 for key in (1, 4, 7, 20, 22, 23, 26, 27, 28, 30, 2000, 2001, 2002, *range(40, 47))}
    props.update({"1": 14000, "4": 1000, "7": 830, "20": .5, "22": 1, "23": 1.5, "2000": 20000, "2001": 2000, "2002": 1000})
    player = cards.PlayerInfo.__new__(cards.PlayerInfo)
    player.roles = {}
    player.data = {"圣遗物榜单": []}
    player.set_role({
        "avatarId": int(metadata["id"]),
        "propMap": {"4001": {"val": "90"}},
        "skillLevelMap": dict(zip(metadata["技能"], [6, 8, 10])),
        "talentIdList": list(range(cons)),
        "fightPropMap": props,
        "equipList": [{
            "itemId": 12517 if name == "达妮卡" else 15517,
            "weapon": {"level": 90},
            # The upstream item ID must work before Enka knows the name hash.
            "flat": {"nameTextMapHash": "not-in-enka", "icon": "not-in-enka", "rankLevel": 5, "weaponStats": [{"statValue": 674}]},
        }],
    })
    return player, player.roles[name]


class Miao73Checks(unittest.TestCase):
    def test_new_roles_parse_with_correct_constellation_talents(self):
        for name in ("达妮卡", "安娜丝塔夏"):
            for cons in range(7):
                with self.subTest(name=name, cons=cons):
                    _, role = make_role(name, cons)
                    self.assertEqual([s["等级"] for s in role["天赋"]], [6, 11 if cons >= 5 else 8, 13 if cons >= 3 else 10])
                    self.assertEqual(len(role["命座"]), cons)
                    self.assertEqual(role["武器"]["名称"], "春潮" if name == "达妮卡" else "银昼")
                    weight, _ = artifacts.get_effective(role)
                    self.assertEqual(weight["元素充能效率"], 100 if name == "达妮卡" else 75)

    def test_valeriy_recharge_weight(self):
        _, role = make_role("达妮卡", 0)
        role["名称"] = "瓦列里"
        weight, _ = artifacts.get_effective(role)
        self.assertEqual(weight["元素充能效率"], 100)

    def test_bundled_images_load_without_network_or_cache_writes(self):
        http = types.ModuleType("zhenxun.utils.http_utils")
        http.AsyncHttpx = types.SimpleNamespace(get_content=AsyncMock(side_effect=AssertionError("unexpected network")))
        with patch.dict(sys.modules, {http.__name__: http}):
            images = importlib.import_module("_miao_73_check.utils.image_utils")
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "must-not-be-created.png"
                for asset in (ROOT / "res/miao_images").glob("*.webp"):
                    result = await images.get_img(f"https://enka.network/ui/{asset.stem}.png", save_path=destination, size=(45, 45), mode="RGBA")
                    self.assertEqual(result.size, (45, 45))
                    self.assertEqual(result.mode, "RGBA")
                    self.assertFalse(destination.exists())
        with patch.object(images, "download_file_checked", AsyncMock(side_effect=AssertionError("unexpected network"))):
            asyncio.run(run())

    def test_portraits_use_full_splash_instead_of_narrow_gacha_cards(self):
        for english in ("Danica", "Anastasya"):
            with Image.open(ROOT / "res/miao_images" / f"UI_Gacha_AvatarImg_{english}.webp") as image:
                self.assertGreater(image.width, image.height)


if __name__ == "__main__":
    unittest.main()
