"""米游社原神探索度数据整理。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import math
from typing import Any


CHINA_TIMEZONE = timezone(timedelta(hours=8))
CHILD_KEYS = ("explorations", "children", "area_exploration_list")
REGION_ORDER = (
    "蒙德",
    "璃月",
    "稻妻",
    "须弥",
    "枫丹",
    "纳塔",
    "挪德卡莱",
    "空之神殿",
    "至冬",
)
CHEST_STATS = (
    "luxurious_chest_number",
    "precious_chest_number",
    "exquisite_chest_number",
    "common_chest_number",
    "magic_chest_number",
)
STAT_LABELS = (
    ("active_day_number", "活跃天数"),
    ("achievement_number", "成就"),
)
PLAYER_STATS = (
    ("active_day_number", "活跃天数"),
    ("achievement_number", "成就达成"),
    ("avatar_number", "获得角色"),
    ("spiral_abyss", "深境螺旋"),
    ("luxurious_chest_number", "华丽宝箱"),
    ("precious_chest_number", "珍贵宝箱"),
    ("exquisite_chest_number", "精致宝箱"),
    ("common_chest_number", "普通宝箱"),
    ("magic_chest_number", "奇馈宝箱"),
    ("way_point_number", "解锁传送点"),
    ("domain_number", "解锁秘境"),
)
OCULUS_STATS = (
    ("anemoculus_number", "风神瞳", "anemo"),
    ("geoculus_number", "岩神瞳", "geo"),
    ("electroculus_number", "雷神瞳", "electro"),
    ("dendroculus_number", "草神瞳", "dendro"),
    ("hydroculus_number", "水神瞳", "hydro"),
    ("pyroculus_number", "火神瞳", "pyro"),
    ("moonoculus_number", "月神瞳", "moon"),
    ("iceculus_number", "冰神瞳", "cryo"),
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _name(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _finite_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, float) or not math.isfinite(value):
        return None
    return value


def _percentage(value: Any) -> tuple[str, float] | None:
    raw = _finite_number(value)
    if raw is None or raw < 0 or raw > 1000:
        return None
    progress = round(raw / 10, 1)
    display = f"{progress:.1f}".rstrip("0").rstrip(".")
    return display, progress


def _children(region: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in CHILD_KEYS:
        value = region.get(key)
        if isinstance(value, (list, tuple)):
            return _items(value)
    return []


def _offerings(value: Any) -> list[dict[str, Any]]:
    result = []
    for offering in _items(value):
        name = _name(offering.get("name"))
        if not name:
            continue
        level = _finite_number(offering.get("level"))
        result.append({"name": name, "level": level})
    return result


def _region_offerings(region: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("shrine_and_oculi_offerings", "offerings"):
        value = region.get(key)
        items = _items(value)
        if items:
            parsed = _offerings(items)
            if parsed:
                return parsed
    return []


def _child_report(child: Mapping[str, Any]) -> dict[str, Any] | None:
    name = _name(child.get("name"))
    if not name:
        return None
    percentage = _percentage(child.get("exploration_percentage"))
    display, progress = percentage if percentage is not None else ("--", 0)
    return {
        "name": name,
        "percentage": display,
        "progress": progress,
        "available": percentage is not None,
    }


def _stat_value(value: Any) -> str | None:
    number = _finite_number(value)
    if number is not None:
        return str(number)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _metrics(value: Any) -> list[dict[str, str]]:
    stats = _mapping(value)
    result = []
    for key, label in STAT_LABELS:
        display = _stat_value(stats.get(key))
        if display is not None:
            result.append({"label": label, "value": display})

    known_chests = []
    for key in CHEST_STATS:
        count = _finite_number(stats.get(key))
        if count is None or count < 0:
            continue
        known_chests.append(count)
    if known_chests:
        result.append({"label": "宝箱合计", "value": str(sum(known_chests))})
    return result


def _player_stats(stats: Mapping[str, Any]) -> list[dict[str, str]]:
    result = [
        {"label": label, "value": _stat_value(stats.get(key)) or "—"}
        for key, label in PLAYER_STATS
    ]
    chest_total = next(
        (
            metric["value"]
            for metric in _metrics(stats)
            if metric["label"] == "宝箱合计"
        ),
        "—",
    )
    result.append({"label": "宝箱合计", "value": chest_total})
    return result


def _homes(value: Any) -> dict[str, Any]:
    source = _items(value) if not isinstance(value, Mapping) else [value]
    source = [home for home in source if home]
    first = source[0] if source else {}
    realms = []
    # 兼容每个洞天一项的旧格式，以及包含 realms 的总览格式。
    for home in source:
        for realm in _items(home.get("realms")) or [home]:
            name = _name(realm.get("name"))
            if name and not any(item["name"] == name for item in realms):
                realms.append({"name": name, "icon": _name(realm.get("icon"))})
    return {
        "available": bool(source),
        "level": _stat_value(first.get("level")) or "—",
        "comfort": _stat_value(first.get("comfort_num")) or "—",
        "comfort_name": _name(first.get("comfort_level_name")),
        "items": _stat_value(first.get("item_num")) or "—",
        "visitors": _stat_value(first.get("visit_num")) or "—",
        "realms": realms,
    }


def build_exploration_report(
    data: Any,
    *,
    uid: Any,
    nickname: Any,
) -> dict[str, Any]:
    """整理 index 接口数据；畸形字段作为缺失值处理，不传播异常。"""
    source = _mapping(data)
    wrapped = _mapping(source.get("data"))
    if wrapped:
        source = wrapped

    regions = []
    source_regions = source.get("world_explorations")
    for region in _items(source_regions):
        name = _name(region.get("name"))
        # 按米游社世界探索卡片的展示分组逆序排列，排除附属地图与供奉项目。
        # 精确匹配并保留各分组原始进度，不用下级区域平均值替代。
        if name not in REGION_ORDER:
            continue
        offerings = _region_offerings(region)
        percentage = _percentage(region.get("exploration_percentage"))
        display, progress = percentage if percentage is not None else ("--", 0)
        children = [
            parsed
            for child in _children(region)
            if (parsed := _child_report(child)) is not None
        ]
        item: dict[str, Any] = {
            "name": name,
            "percentage": display,
            "progress": progress,
            "available": percentage is not None,
            "offerings": offerings,
            "children": children,
            "icon": _name(region.get("inner_icon") or region.get("icon")),
            "level_label": "声望等级" if region.get("type") == "Reputation" else "",
            "tribes": [
                {
                    "name": _name(tribe.get("name")),
                    "level": _stat_value(tribe.get("level")) or "—",
                }
                for tribe in _items(
                    _mapping(region.get("natan_reputation")).get("tribal_list")
                )
                if _name(tribe.get("name"))
            ],
        }
        level = _finite_number(region.get("level"))
        if level is not None:
            item["level"] = level
        regions.append(item)

    regions.sort(key=lambda item: REGION_ORDER.index(item["name"]))

    stats = _mapping(source.get("stats"))
    role = _mapping(source.get("role"))
    return {
        "title": "原神探索度",
        "uid": str(uid),
        "nickname": str(nickname or "旅行者"),
        "regions": regions,
        "completed": sum(
            region["available"] and region["progress"] >= 100 for region in regions
        ),
        "total": len(regions),
        "metrics": _metrics(source.get("stats")),
        "player_stats": _player_stats(stats),
        "oculi": [
            {
                "label": label,
                "value": _stat_value(stats.get(key)) or "—",
                "element": element,
            }
            for key, label, element in OCULUS_STATS
            if key in stats
        ],
        "homes": _homes(source.get("homes")),
        "player_level": _stat_value(role.get("level")) or "—",
        "empty_message": "" if regions else "暂无探索度数据",
        "updated_at": datetime.now(CHINA_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
    }
