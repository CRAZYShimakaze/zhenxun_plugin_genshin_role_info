"""原神战绩命令解析和米游社数据整理，不依赖机器人运行状态。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, NamedTuple


BATTLE_COMMAND_PATTERN = (
    r"^[#＃/]?(?:查询|查)?(?:原神)?\s*(本期|上期)?\s*"
    r"(深境螺旋|深渊|幻想真境剧诗|幻想真境|剧诗|幽境危战|幽境|危战)"
    r"\s*(本期|上期)?$"
)
TITLES = {
    "abyss": ("深境螺旋", "SPIRAL ABYSS"),
    "theater": ("幻想真境剧诗", "IMAGINARIUM THEATER"),
    "stygian": ("幽境危战", "STYGIAN ONSLAUGHT"),
}
CHINA_TIMEZONE = timezone(timedelta(hours=8))
ROLE_INFO_PATH = Path(__file__).parent / "res" / "json_data" / "role_info.json"
ELEMENTS = {
    "pyro": "火",
    "fire": "火",
    "hydro": "水",
    "water": "水",
    "electro": "雷",
    "electric": "雷",
    "cryo": "冰",
    "ice": "冰",
    "anemo": "风",
    "wind": "风",
    "geo": "岩",
    "rock": "岩",
    "dendro": "草",
    "grass": "草",
}


class BattleQuery(NamedTuple):
    kind: str
    schedule_type: int


def parse_battle_command(text: str) -> BattleQuery | None:
    match = re.fullmatch(BATTLE_COMMAND_PATTERN, text.strip())
    if not match:
        return None
    before, name, after = match.groups()
    if before and after and before != after:
        return None
    kind = (
        "abyss"
        if name in {"深境螺旋", "深渊"}
        else "stygian"
        if name in {"幽境危战", "幽境", "危战"}
        else "theater"
    )
    return BattleQuery(kind, 2 if (before or after) == "上期" else 1)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def format_duration(value: Any) -> str:
    if value is None or value == "":
        return "—"
    seconds = max(0, _int(value))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _date_range(schedule: dict) -> str:
    values = []
    for key in ("start_time", "end_time"):
        try:
            stamp = int(schedule.get(key, 0))
            if stamp <= 0:
                return ""
            values.append(
                datetime.fromtimestamp(stamp, CHINA_TIMEZONE).strftime("%Y.%m.%d")
            )
        except (ValueError, TypeError, OverflowError, OSError):
            return ""
    return " — ".join(values)


@lru_cache(maxsize=1)
def _role_metadata() -> dict[str, dict]:
    try:
        source = json.loads(ROLE_INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result = {}
    for name, metadata in source.items():
        ids = metadata.get("id", [])
        ids = ids if isinstance(ids, list) else [ids]
        for role_id in ids:
            result[str(role_id)] = {**metadata, "name": name}
    return result


def _avatar(data: dict) -> dict:
    role_id = str(data.get("avatar_id") or data.get("id") or "")
    metadata = _role_metadata().get(role_id, {})
    name = str(data.get("name") or metadata.get("name") or "未知角色")
    element = str(data.get("element") or metadata.get("元素") or "")
    icon = str(data.get("image") or data.get("icon") or data.get("avatar_icon") or "")
    if not icon and metadata.get("英文名"):
        icon = f"https://enka.network/ui/UI_AvatarIcon_{metadata['英文名']}.png"
    return {
        "id": role_id,
        "name": name,
        "icon": icon,
        "element": ELEMENTS.get(element.lower(), element),
        "level": _int(data.get("level")),
        "rarity": _int(data.get("rarity")),
    }


def _avatars(value: Any) -> list[dict]:
    return [_avatar(item) for item in _items(value)]


def _metric(label: str, value: Any) -> dict:
    return {"label": label, "value": "—" if value is None else str(value)}


def _highlight(label: str, data: dict, unit: str = "") -> dict:
    value = data.get("value")
    try:
        value = f"{int(value):,}"
    except (ValueError, TypeError, OverflowError):
        value = str(value or "—")
    return {"label": label, "value": _avatar(data)["name"], "note": f"{value}{unit}"}


def _select_entry(kind: str, data: dict, schedule_type: int) -> dict | None:
    entries = _items(data.get("data"))
    if kind == "theater":
        # 剧诗明确标记本期/上期；不要把仅返回的本期当作上期。
        explicit = [
            entry
            for entry in entries
            if _dict(entry.get("schedule")).get("schedule_type") is not None
        ]
        if explicit:
            return next(
                (
                    entry
                    for entry in explicit
                    if _int(entry["schedule"].get("schedule_type")) == schedule_type
                ),
                None,
            )
    # 幽境接口同时返回多个赛期，schedule_type 请求参数不会筛选结果。
    entries = sorted(
        entries,
        key=lambda e: _int(_dict(e.get("schedule")).get("start_time")),
        reverse=True,
    )
    return entries[schedule_type - 1] if len(entries) >= schedule_type else None


def build_battle_report(
    kind: str,
    data: dict,
    *,
    uid: str,
    nickname: str,
    schedule_type: int = 1,
) -> dict:
    if (
        kind not in TITLES
        or type(schedule_type) is not int
        or schedule_type not in (1, 2)
    ):
        raise ValueError("无效的原神战绩查询参数")
    if not isinstance(data, dict):
        raise ValueError("米游社战绩数据格式异常")
    title, eyebrow = TITLES[kind]
    report = {
        "kind": kind,
        "title": title,
        "eyebrow": eyebrow,
        "period_label": "本期" if schedule_type == 1 else "上期",
        "date_range": "",
        "uid": str(uid),
        "nickname": str(nickname or "旅行者"),
        "hero": {"label": "挑战记录", "value": "—", "unit": "", "note": ""},
        "metrics": [],
        "floors": [],
        "acts": [],
        "challenges": [],
        "highlights": [],
        "notes": [],
        "empty_message": "",
    }
    if data.get("is_unlock") is False:
        report["empty_message"] = f"尚未解锁{title}"
        return report
    if kind == "abyss":
        _build_abyss(report, data)
    else:
        entry = _select_entry(kind, data, schedule_type)
        if entry is None:
            report["empty_message"] = f"{report['period_label']}暂无{title}记录"
            return report
        report["date_range"] = _date_range(_dict(entry.get("schedule")))
        if kind == "theater":
            _build_theater(report, entry)
        else:
            _build_stygian(report, entry)
    return report


def _build_abyss(report: dict, data: dict) -> None:
    report["date_range"] = _date_range(data)
    stars = _int(data.get("total_star"))
    report["hero"] = {
        "label": "总星数",
        "value": str(stars),
        "unit": "/ 36",
        "note": "满星通关" if stars == 36 else "深境挑战记录",
    }
    report["metrics"] = [
        _metric("挑战次数", data.get("total_battle_times")),
        _metric("胜利次数", data.get("total_win_times")),
        _metric("最高进度", data.get("max_floor") or "—"),
    ]
    for floor in sorted(_items(data.get("floors")), key=lambda f: _int(f.get("index"))):
        chambers = []
        for level in sorted(
            _items(floor.get("levels")), key=lambda item: _int(item.get("index"))
        ):
            teams = []
            for battle in sorted(
                _items(level.get("battles")), key=lambda b: _int(b.get("index"))
            ):
                half = _int(battle.get("index"))
                teams.append(
                    {
                        "label": {1: "上半", 2: "下半"}.get(half, f"第{half}队"),
                        "avatars": _avatars(battle.get("avatars")),
                    }
                )
            chambers.append(
                {
                    "index": _int(level.get("index")),
                    "star": _int(level.get("star")),
                    "max_star": _int(level.get("max_star"), 3),
                    "teams": teams,
                }
            )
        report["floors"].append(
            {
                "index": _int(floor.get("index")),
                "star": _int(floor.get("star")),
                "max_star": _int(floor.get("max_star"), 9),
                "chambers": chambers,
            }
        )
    for key, label, unit in (
        ("damage_rank", "最高伤害", ""),
        ("defeat_rank", "击破最多", " 次"),
        ("reveal_rank", "出战最多", " 次"),
    ):
        ranks = _items(data.get(key))
        if ranks:
            report["highlights"].append(_highlight(label, ranks[0], unit))
    if data.get("skipped_floor") or data.get("is_just_skipped_floor"):
        report["notes"].append("部分楼层为跳层完成，无分间战斗记录。")
    if not report["floors"]:
        if stars or _int(data.get("total_battle_times")):
            report["notes"].append("暂无可展示的分间战斗详情。")
        else:
            report["empty_message"] = f"{report['period_label']}暂无深境螺旋挑战记录"


def _build_theater(report: dict, entry: dict) -> None:
    detail = _dict(entry.get("detail"))
    stat = _dict(entry.get("stat")) or _dict(detail.get("detail_stat"))
    fight = _dict(detail.get("fight_statisic")) or _dict(detail.get("fight_statistic"))
    rounds = _items(detail.get("rounds_data"))
    if entry.get("has_data") is False or (not stat and not rounds):
        report["empty_message"] = f"{report['period_label']}暂无幻想真境剧诗演出记录"
        return
    max_round = _int(stat.get("max_round_id"))
    report["hero"] = {
        "label": "演出进度",
        "value": str(max_round),
        "unit": "幕",
        "note": "幻想真境演出记录",
    }
    report["metrics"] = [
        _metric("挑战难度", stat.get("difficulty_id")),
        _metric("获得徽章", stat.get("medal_num")),
        _metric(
            "战斗总耗时",
            format_duration(fight.get("total_use_time"))
            if fight.get("is_show_battle_stats") is not False
            else "—",
        ),
    ]
    extra = 0
    for item in rounds:
        if item.get("is_tarot"):
            extra += 1
            label = f"额外演出 {extra}"
        else:
            label = f"第 {_int(item.get('round_id')):02d} 幕"
        report["acts"].append(
            {
                "label": label,
                "medal": bool(item.get("is_get_medal")),
                "avatars": _avatars(item.get("avatars")),
            }
        )
    if extra:
        report["notes"].append(f"含 {extra} 幕额外演出，单独列出。")
    if not rounds:
        report["notes"].append("暂无本次演出的分幕阵容详情。")
    if fight.get("is_show_battle_stats") is not False:
        for key, label, unit in (
            ("max_damage_avatar", "最高伤害", ""),
            ("max_defeat_avatar", "击破最多", " 次"),
            ("max_take_damage_avatar", "承受伤害", ""),
        ):
            value = _dict(fight.get(key))
            if value:
                report["highlights"].append(_highlight(label, value, unit))


def _build_stygian(report: dict, entry: dict) -> None:
    selected_mode = None
    selected_label = ""
    for key, label in (("single", "单人挑战"), ("mp", "联机挑战")):
        mode = _dict(entry.get(key))
        best = _dict(mode.get("best"))
        raw_challenges = _items(mode.get("challenge"))
        has_data = mode.get("has_data") is not False and bool(best or raw_challenges)
        if not has_data:
            report["challenges"].append(
                {"label": label, "summary": "暂无挑战记录", "bosses": []}
            )
            continue
        if selected_mode is None:
            selected_mode, selected_label = mode, label
        bosses = []
        for challenge in raw_challenges:
            monster = _dict(challenge.get("monster"))
            bosses.append(
                {
                    "name": str(
                        challenge.get("name") or monster.get("name") or "首领挑战"
                    ),
                    "icon": str(monster.get("icon") or ""),
                    "second": format_duration(challenge.get("second")),
                    "avatars": _avatars(challenge.get("teams")),
                }
            )
        report["challenges"].append(
            {
                "label": label,
                "summary": f"难度 {best.get('difficulty', '—')} · 总耗时 {format_duration(best.get('second'))}",
                "bosses": bosses,
            }
        )
    if selected_mode is None:
        report["empty_message"] = f"{report['period_label']}暂无幽境危战挑战记录"
        return
    best = _dict(selected_mode.get("best"))
    report["hero"] = {
        "label": f"{selected_label[:2]}最佳总耗时",
        "value": format_duration(best.get("second")),
        "unit": "",
        "note": "幽境危战挑战记录",
    }
    report["metrics"] = [
        _metric("最佳难度", best.get("difficulty")),
        _metric("完成挑战", len(_items(selected_mode.get("challenge")))),
        _metric("挑战方式", selected_label[:2]),
    ]
