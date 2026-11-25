"""Group distributions for the role panels."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from PIL import Image, ImageDraw

DamageCalculator = Callable[..., Mapping[str, tuple[str, ...]] | None]


def _number(value: object) -> float | None:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _read_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_damage(calculator: DamageCalculator, role: dict) -> tuple[str, float] | None:
    try:
        result = calculator(role, default_only=True)
    except Exception as error:
        logging.getLogger(__name__).debug("面板排名伤害计算失败: %s", type(error).__name__)
        return None
    if result:
        title, values = next(iter(result.items()))
        if values and not getattr(values, "is_text", False):
            if (value := _number(values[0])) is not None:
                return title, value
    return None


@dataclass(frozen=True)
class PanelRanks:
    scores: tuple[float, ...]
    damage: tuple[str, float] | None = None
    damages: tuple[float, ...] = ()
    height: ClassVar[int] = 430

    def render(self, score: float, score_title: str, mask_path: str | Path, get_font) -> Image.Image:
        width = 948
        panel = Image.new("RGBA", (width, self.height))
        for part, top, height in (
            ("top", 0, 60),
            ("body", 60, self.height - 80),
            ("bottom", self.height - 20, 20),
        ):
            with Image.open(Path(mask_path) / f"遮罩{part}.png") as mask:
                panel.alpha_composite(mask.convert("RGBA").resize((width, height)), (0, top))

        ink = Image.new("RGBA", panel.size)
        draw = ImageDraw.Draw(ink)
        draw.text((24, 13), "群内排名", font=get_font(30), fill="#ead59f")
        line = (255, 255, 255, 75)
        for y in (60, 116, 357):
            draw.line((0, y, width, y), fill=line, width=2)

        if self.damage:
            title, value = self.damage
            draw.line((474, 60, 474, self.height - 1), fill=line, width=2)
            _draw_chart(
                panel, draw, get_font, 0, 474, "伤害排名", f"{title} · 期望",
                value, self.damages, damage=True,
            )
        _draw_chart(
            panel, draw, get_font, 474 if self.damage else 0, 474 if self.damage else width,
            f"{score_title}排名", f"{score_title.removesuffix('评分')}总分",
            float(score), self.scores,
        )
        return Image.alpha_composite(panel, ink)


def _draw_chart(panel, draw, get_font, x, width, title, detail, value, peers, *, damage=False):
    muted, gold = "#e1e2e4", "#ead59f"
    values = sorted((*peers, value))
    count = len(values)
    rank = 1 + sum(sample > value for sample in values)
    minimum_step = max(1.0, values[-1]) / 4
    step_base = 10 ** math.floor(math.log10(minimum_step))
    step = next(step_base * factor for factor in (1, 2, 2.5, 5, 10)
                if step_base * factor >= minimum_step)
    draw.text((x + width / 2, 88), title, font=get_font(29), fill="white", anchor="mm")
    detail_font = get_font(22)
    while draw.textlength(detail, font=detail_font) > width - 36 and len(detail) > 2:
        detail = detail[:-2] + "…"
    draw.text((x + width / 2, 140), detail, font=detail_font, fill=muted, anchor="mm")

    left, right, top, bottom = x + 74, x + width - 28, 193, 313
    axis_font = get_font(19)
    for tick in range(5):
        label = tick * step
        label_text = f"{label / 10000:g}万" if label >= 10000 else f"{label:g}"
        y = round(bottom - (bottom - top) * tick / 4)
        draw.line((left, y, right, y), fill=(255, 255, 255, 45), width=1)
        draw.text((left - 9, y), label_text, font=axis_font, fill=muted, anchor="rm")
    points = [
        (
            left + (right - left) * index / (count - 1) if count > 1 else (left + right) / 2,
            bottom - (bottom - top) * (sample / step) / 4,
        )
        for index, sample in enumerate(values)
    ]
    # Supersample the curve and marker so shallow slopes retain subpixel detail.
    scale, padding = 4, 6
    origin_x, origin_y = left - padding, top - padding
    curve_size = (right - left + padding * 2, bottom - top + padding * 2)
    curve = Image.new("RGBA", tuple(size * scale for size in curve_size))
    curve_draw = ImageDraw.Draw(curve)
    curve_points = [
        ((px - origin_x) * scale, (py - origin_y) * scale) for px, py in points
    ]
    baseline = (bottom - origin_y) * scale
    if count > 1:
        curve_draw.polygon(
            [(padding * scale, baseline), *curve_points,
             ((right - origin_x) * scale, baseline)],
            fill=(130, 177, 196, 63) if damage else (211, 180, 106, 61),
        )
        curve_draw.line(
            curve_points, fill="#bed7df" if damage else "#e0c88e",
            width=3 * scale, joint="curve",
        )
        draw.text((left, 327), f"第{count}名", font=axis_font, fill=muted)
    draw.text((right if count > 1 else (left + right) / 2, 327), "第1名",
              font=axis_font, fill=muted, anchor="rt" if count > 1 else "mt")
    px, py = points[-rank]
    marker_x, marker_y = curve_points[-rank]
    curve_draw.line((marker_x, marker_y, marker_x, baseline), fill=gold, width=2 * scale)
    radius = 5 * scale
    curve_draw.ellipse(
        (marker_x - radius, marker_y - radius, marker_x + radius, marker_y + radius),
        fill=gold,
    )
    panel.alpha_composite(
        curve.resize(curve_size, Image.Resampling.LANCZOS), (origin_x, origin_y),
    )
    label = f"{value:,.2f}".rstrip("0").rstrip(".") if damage else f"{value:,.2f}"
    label_font = get_font(26, "number.ttf")
    label_width = draw.textlength(label, font=label_font)
    label_x = max(left, min(px - label_width / 2, right - label_width))
    draw.text((label_x, py - 8), label, font=label_font, fill="white",
              anchor="lb", stroke_width=1, stroke_fill="#454038")
    draw.text((x + 25, 389), f"第 {rank} / {count} 名", font=get_font(30), fill="white", anchor="lm")
    draw.text((right, 389), f"前 {rank / count:.1%}", font=get_font(27), fill=gold, anchor="rm")


@lru_cache(maxsize=4096)
def _peer_values(
    path: Path, cache_version: tuple[int, int, int, int], role_name: str,
    damage_calculator: DamageCalculator | None, enemy_level: int | float | str | None,
) -> tuple[float | None, float | None]:
    """Reuse calculation results until the underlying panel cache changes."""
    roles = _read_object(path).get("角色")
    peer = roles.get(role_name) if isinstance(roles, dict) else None
    if not isinstance(peer, dict) or not isinstance(peer.get("属性"), dict):
        return None, None
    score = _number(peer.get("评分"))
    if not damage_calculator:
        return score, None
    # Compare every panel at the enemy level used by the displayed panel.
    peer.pop("敌人等级", None)
    if enemy_level is not None:
        peer["敌人等级"] = enemy_level
    damage = _default_damage(damage_calculator, peer)
    return score, damage[1] if damage else None


def _collect_panel_ranks(
    members: Iterable[Mapping], directory: Path, uid: str, role_name: str, role: dict,
    damage_calculator: DamageCalculator | None,
) -> PanelRanks | None:
    uid_map = _read_object(directory / "qq2uid.json")
    member_uids = {
        str(uid_map.get(str(member.get("user_id")), ""))
        for member in members
        if isinstance(member, Mapping)
    }
    if uid not in member_uids:
        return None
    own_damage = _default_damage(damage_calculator, role) if damage_calculator else None
    enemy_level = role.get("敌人等级")
    if not isinstance(enemy_level, (int, float, str)):
        enemy_level = None
    scores, damages = [], []
    for peer_uid in member_uids - {uid}:
        if not peer_uid.isascii() or not peer_uid.isdecimal():
            continue
        path = directory / f"{peer_uid}.json"
        try:
            status = path.stat()
        except OSError:
            continue
        score, damage = _peer_values(
            path, (status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns),
            role_name, damage_calculator if own_damage else None, enemy_level,
        )
        if score is not None:
            scores.append(score)
        if damage is not None:
            damages.append(damage)
    return PanelRanks(tuple(scores), own_damage, tuple(damages))


async def get_panel_ranks(
    event, directory: str | Path, uid: int | str, role_name: str, role: dict,
    damage_calculator: DamageCalculator | None = None,
) -> PanelRanks | None:
    if not isinstance(event, GroupMessageEvent):
        return None
    try:
        members = await get_bot(str(event.self_id)).get_group_member_list(group_id=event.group_id)
        return await asyncio.to_thread(
            _collect_panel_ranks, members or [], Path(directory), str(uid), role_name, role,
            damage_calculator,
        )
    except Exception as error:
        logging.getLogger(__name__).warning("群内面板排名读取失败: %s", type(error).__name__)
        return None
