from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
from pathlib import Path
from typing import Any


RankEntry = dict[str, Any]
DamageCalculator = Callable[[dict], Mapping[str, tuple[str, ...]] | None]

def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def select_damage_metric(
    damage: Mapping[str, tuple[str, ...]] | None,
    damage_index: int,
) -> tuple[str, float, float | None] | None:
    """Select a one-based row from the rendered role damage table."""
    rows = [item for item in (damage or {}).items() if item[0] != "额外说明"]
    if damage_index < 1 or damage_index > len(rows):
        return None
    title, values = rows[damage_index - 1]
    if not values or (expected := _number(values[0])) is None:
        return None
    critical = _number(values[1]) if len(values) > 1 else None
    return title, expected, critical


def _total_stat(properties: Mapping[str, object], stat: str) -> float:
    return float(properties.get(f"基础{stat}", 0) or 0) + float(
        properties.get(f"额外{stat}", 0) or 0
    )


def _percent(value: object) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def build_rank_entry(
    qq: int,
    nickname: str,
    role_data: dict,
    metric: str,
    damage: Mapping[str, tuple[str, ...]] | None = None,
    damage_index: int | None = None,
) -> RankEntry | None:
    properties = role_data.get("属性")
    if not isinstance(properties, Mapping):
        return None

    score = _number(role_data.get("评分"))
    if metric == "评分":
        if score is None:
            return None
        value = score
        damage_title = None
    elif metric == "伤害":
        if damage_index is None:
            return None
        damage_metric = select_damage_metric(damage, damage_index)
        if damage_metric is None:
            return None
        damage_title, value, _ = damage_metric
    else:
        raise ValueError(f"不支持的排行类型: {metric}")

    rows = [
        ("生命值", f"{_total_stat(properties, '生命'):,.0f}"),
        ("暴击率", _percent(properties.get("暴击率"))),
        ("暴击伤害", _percent(properties.get("暴击伤害"))),
        ("元素精通", f"{float(properties.get('元素精通', 0) or 0):,.0f}"),
        ("元素充能效率", _percent(properties.get("元素充能效率"))),
    ]

    constellations = role_data.get("命座")
    rank = len(constellations) if isinstance(constellations, list) else 0
    weapon = role_data.get("武器")
    weapon_info = (
        {
            "星级": weapon.get("星级", 1),
            "图标": weapon.get("图标", ""),
            "图标链接": weapon.get("图标链接", ""),
        }
        if isinstance(weapon, Mapping)
        else {}
    )
    return {
        "qq": qq,
        "nickname": nickname,
        "rank": rank,
        "value": value,
        "rows": rows,
        "weapon": weapon_info,
        "damage_title": damage_title,
    }


def collect_role_rank_entries(
    members: Iterable[Mapping[str, object]],
    uid_map: Mapping[str, object],
    player_info_dir: str | Path,
    role_name: str,
    metric: str,
    damage_calculator: DamageCalculator | None = None,
    damage_index: int | None = None,
    limit: int = 16,
) -> list[RankEntry]:
    entries: list[RankEntry] = []
    player_info_dir = Path(player_info_dir)
    for member in members:
        qq_value = member.get("user_id")
        try:
            qq = int(str(qq_value))
        except (TypeError, ValueError):
            continue
        uid = uid_map.get(str(qq))
        if not uid:
            continue
        try:
            payload = json.loads(
                (player_info_dir / f"{uid}.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        roles = payload.get("角色")
        if not isinstance(roles, Mapping) or not isinstance(
            role_data := roles.get(role_name), dict
        ):
            continue
        damage = (
            damage_calculator(role_data)
            if metric == "伤害" and damage_calculator
            else None
        )
        nickname = str(member.get("card") or member.get("nickname") or qq)
        try:
            if entry := build_rank_entry(
                qq,
                nickname,
                role_data,
                metric,
                damage,
                damage_index,
            ):
                entries.append(entry)
        except (TypeError, ValueError):
            continue

    entries.sort(key=lambda item: (-float(item["value"]), int(item["qq"])))
    return entries[:limit]
