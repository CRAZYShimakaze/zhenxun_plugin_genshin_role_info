from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple


PLAYER_INFO_DIR = Path(__file__).parent / "user_data" / "player_info"
ROLE_INFO_PATH = Path(__file__).parent / "res" / "json_data" / "role_info.json"

PROPERTY_NAMES = {
    2: "生命值",
    3: "百分比生命值",
    5: "攻击力",
    6: "百分比攻击力",
    8: "防御力",
    9: "百分比防御力",
    20: "暴击率",
    22: "暴击伤害",
    23: "元素充能效率",
    26: "治疗加成",
    27: "受治疗加成",
    28: "元素精通",
    30: "物理伤害加成",
    40: "火元素伤害加成",
    41: "雷元素伤害加成",
    42: "水元素伤害加成",
    43: "草元素伤害加成",
    44: "风元素伤害加成",
    45: "岩元素伤害加成",
    46: "冰元素伤害加成",
}
DAMAGE_INDEX = {30: 0, 40: 1, 41: 2, 42: 3, 43: 4, 44: 5, 45: 6, 46: 7}
ELEMENT_NAMES = {
    "pyro": "火",
    "fire": "火",
    "electro": "雷",
    "electric": "雷",
    "hydro": "水",
    "water": "水",
    "dendro": "草",
    "grass": "草",
    "anemo": "风",
    "wind": "风",
    "geo": "岩",
    "rock": "岩",
    "cryo": "冰",
    "ice": "冰",
}
ACTIVE_TALENT_IDS = {
    "神里绫华": ("10024", "10018", "10019"),
    "莫娜": ("10411", "10412", "10415"),
}


class GenshinSyncResult(NamedTuple):
    status: Literal["skipped", "bound", "synced", "failed"]
    uid: str | None = None
    role_count: int = 0
    error: str = ""


def _load_role_metadata() -> dict[str, dict]:
    with ROLE_INFO_PATH.open(encoding="utf-8") as file:
        return json.load(file)


ROLE_METADATA = _load_role_metadata()


def _role_name(role_id: Any, fallback: str = "") -> str:
    role_id = str(role_id)
    if role_id == "10000005":
        return "空"
    if role_id == "10000007":
        return "荧"
    for name, metadata in ROLE_METADATA.items():
        ids = metadata.get("id", [])
        ids = [ids] if isinstance(ids, str) else ids
        if role_id in {str(item) for item in ids}:
            return name
    return fallback if fallback in ROLE_METADATA else ""


def _number(value: Any, *, ratio: bool = False) -> int | float:
    if value in (None, ""):
        return 0
    text = str(value).strip().replace(",", "").lstrip("+")
    is_percent = text.endswith("%")
    number = float(text.rstrip("%"))
    if ratio and is_percent:
        number /= 100
    number = round(number, 4 if ratio else 3)
    return int(number) if number.is_integer() else number


def _property_name(property_type: Any, property_map: dict) -> str:
    property_type = int(property_type)
    if property_type in PROPERTY_NAMES:
        return PROPERTY_NAMES[property_type]
    info = property_map.get(str(property_type), property_map.get(property_type, {}))
    name = info.get("name", "") if isinstance(info, dict) else ""
    return {
        "生命值百分比": "百分比生命值",
        "攻击力百分比": "百分比攻击力",
        "防御力百分比": "百分比防御力",
    }.get(name, name)


def _properties(items: list[dict]) -> dict[int, dict]:
    return {
        int(item["property_type"]): item for item in items if "property_type" in item
    }


def _asset_name(value: Any) -> str:
    return str(value or "").split("?", 1)[0].rsplit("/", 1)[-1].removesuffix(".png")


def _icon_url(value: Any) -> str:
    value = str(value or "")
    return value if value.startswith("https://") else ""


def _convert_attributes(items: list[dict]) -> dict:
    properties = _properties(items)

    def value(property_type: int, field: str = "final", *, ratio: bool = False):
        return _number(properties.get(property_type, {}).get(field), ratio=ratio)

    damage = [0] * 8
    for property_type, index in DAMAGE_INDEX.items():
        damage[index] = value(property_type, ratio=True)
    return {
        "基础生命": value(2000, "base"),
        "额外生命": value(2000, "add"),
        "基础攻击": value(2001, "base"),
        "额外攻击": value(2001, "add"),
        "基础防御": value(2002, "base"),
        "额外防御": value(2002, "add"),
        "暴击率": value(20, ratio=True),
        "暴击伤害": value(22, ratio=True),
        "元素精通": value(28),
        "元素充能效率": value(23, ratio=True),
        "治疗加成": value(26, ratio=True),
        "受治疗加成": value(27, ratio=True),
        "伤害加成": damage,
    }


def _convert_talents(
    skills: list[dict], metadata: dict, role_name: str
) -> list[dict]:
    talents = []
    skill_icons = metadata.get("技能", {})
    active_skills = [
        skill for skill in skills if int(skill.get("skill_type", 0)) == 1
    ]
    if talent_ids := ACTIVE_TALENT_IDS.get(role_name):
        skills_by_id = {
            str(skill.get("skill_id", "")): skill for skill in active_skills
        }
        selected = [skills_by_id.get(skill_id) for skill_id in talent_ids]
        if all(selected):
            active_skills = selected
    elif len(active_skills) > 3:
        active_skills = [*active_skills[:2], active_skills[-1]]
    for skill in active_skills:
        skill_id = str(skill.get("skill_id", ""))
        source = skill.get("icon")
        icon = skill_icons.get(skill_id) or _asset_name(source)
        talents.append(
            {
                "等级": int(skill.get("level", 1)),
                "图标": icon,
                "图标链接": _icon_url(source),
            }
        )
    if len(talents) < 3:
        raise ValueError("角色主动天赋数据不足")
    return talents[:3]


def _convert_constellations(
    data: dict, metadata: dict
) -> tuple[list[str], list[str]]:
    count = int(data.get("base", {}).get("actived_constellation_num", 0))
    active_items = [
        item
        for item in data.get("constellations", [])
        if item.get("is_actived")
    ]
    active = [_asset_name(item.get("icon")) for item in active_items]
    if len(active) == count and all(active):
        return active, [_icon_url(item.get("icon")) for item in active_items]
    return list(metadata.get("命座", []))[:count], []


def _convert_weapon(data: dict, property_map: dict, weapon_type: str) -> dict:
    main = data.get("main_property") or {}
    sub = data.get("sub_property") or {}
    icon = str(data.get("icon") or "")
    return {
        "名称": data.get("name", "未知武器"),
        "图标": _asset_name(icon),
        "图标链接": _icon_url(icon),
        "类型": weapon_type,
        "等级": int(data.get("level", 1)),
        "星级": int(data.get("rarity", 1)),
        "突破等级": int(data.get("promote_level", 0)),
        "精炼等级": int(data.get("affix_level", 1)),
        "基础攻击": _number(main.get("final")),
        "副属性": {
            "属性名": _property_name(sub.get("property_type", 0), property_map)
            or "无属性",
            "属性值": _number(sub.get("final")),
        },
        "特效": "待补充",
    }


def _convert_artifact(data: dict, property_map: dict) -> dict:
    main = data.get("main_property") or {}
    artifact_set = data.get("set") or {}
    icon = data.get("icon")
    return {
        "名称": data.get("name", "未知圣遗物"),
        "图标": _asset_name(icon),
        "图标链接": _icon_url(icon),
        "部位": data.get("pos_name", ""),
        "所属套装": artifact_set.get("name", "")
        if isinstance(artifact_set, dict)
        else "",
        "等级": int(data.get("level", 0)),
        "星级": int(data.get("rarity", 1)),
        "主属性": {
            "属性名": _property_name(main.get("property_type", 0), property_map),
            "属性值": _number(main.get("value")),
        },
        "词条": [
            {
                "属性名": _property_name(item.get("property_type", 0), property_map),
                "属性值": _number(item.get("value")),
            }
            for item in data.get("sub_property_list", [])
        ],
    }


def convert_character(data: dict, property_map: dict) -> dict:
    base = data.get("base") or {}
    name = _role_name(base.get("id"), str(base.get("name", "")))
    if not name:
        raise ValueError(f"不支持的角色 ID: {base.get('id', 'unknown')}")
    metadata = ROLE_METADATA[name]
    element = str(base.get("element", ""))
    element = ELEMENT_NAMES.get(element.lower(), element)
    properties = []
    for key in (
        "base_properties",
        "extra_properties",
        "element_properties",
        "selected_properties",
    ):
        properties.extend(data.get(key, []))
    constellations, constellation_urls = _convert_constellations(data, metadata)
    return {
        "名称": name,
        "等级": int(base.get("level", 1)),
        "元素": element,
        "天赋": _convert_talents(data.get("skills", []), metadata, name),
        "命座": constellations,
        "命座图标链接": constellation_urls,
        "属性": _convert_attributes(properties),
        "武器": _convert_weapon(
            data.get("weapon") or {}, property_map, metadata.get("武器", "")
        ),
        "圣遗物": [
            _convert_artifact(item, property_map) for item in data.get("relics", [])
        ],
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def overwrite_uid_binding(qq_id: int, uid: str) -> None:
    path = PLAYER_INFO_DIR / "qq2uid.json"
    bindings = _read_json(path)
    bindings[str(qq_id)] = int(uid)
    _write_json(path, bindings)


def bind_single_genshin_uid(qq_id: int, user: dict) -> GenshinSyncResult:
    roles = user.get("game_roles", {}).get("genshin", [])
    if not isinstance(roles, list) or len(roles) != 1:
        return GenshinSyncResult("skipped")
    uid = str(roles[0].get("game_uid", ""))
    region = str(roles[0].get("region", ""))
    if not uid.isdigit() or not region:
        return GenshinSyncResult(
            "failed", uid or None, error="原神 UID 或区服信息不完整"
        )
    overwrite_uid_binding(qq_id, uid)
    return GenshinSyncResult("bound", uid)


def save_character_cache(uid: str, account_role: dict, detail_data: dict) -> int:
    property_map = detail_data.get("property_map") or {}
    roles = {}
    for item in detail_data.get("list", []):
        try:
            role = convert_character(item, property_map)
        except (KeyError, TypeError, ValueError):
            continue
        roles[role["名称"]] = role
    if not roles:
        raise ValueError("米游社未返回可用的原神角色详情")

    path = PLAYER_INFO_DIR / f"{uid}.json"
    data = _read_json(path)
    player = data.setdefault("玩家信息", {})
    player.update(
        {
            "昵称": account_role.get("nickname", "unknown"),
            "等级": account_role.get("level", "unknown"),
            "角色列表": list(roles),
            "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    data["角色"] = roles
    data["圣遗物榜单"] = []
    data["大毕业圣遗物"] = 0
    data["小毕业圣遗物"] = 0
    data.setdefault("圣遗物列表", [[], [], [], [], []])
    _write_json(path, data)
    return len(roles)


async def sync_single_genshin_uid(
    qq_id: int,
    user: dict,
    api: Any,
    captcha_notifier: Callable[[str], Awaitable[None]] | None = None,
) -> GenshinSyncResult:
    binding = bind_single_genshin_uid(qq_id, user)
    if binding.status != "bound":
        return binding
    roles = user["game_roles"]["genshin"]
    account_role = roles[0]
    uid = str(binding.uid)
    region = str(account_role.get("region", ""))

    try:
        request_args: dict[str, Any] = {"uid": uid, "region": region}
        if captcha_notifier is not None:
            request_args["captcha_notifier"] = captcha_notifier
        detail_data = await api.get_genshin_character_details(user, **request_args)
        count = save_character_cache(uid, account_role, detail_data or {})
    except Exception as error:
        return GenshinSyncResult("failed", uid, error=str(error))
    return GenshinSyncResult("synced", uid, count)
