from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from ..utils.card_utils import bg_path, get_font, other_path, weapon_path
from ..utils.image_utils import get_img, load_image
from ..utils.rank_utils import RankEntry
from .draw_artifact_card import artifact_url, get_icon_url, role_info_json

_PLUGIN_DATA = Path(__file__).resolve().parents[1] / "user_data"
_WIDTH = 1040
_ROW_START = 230
_ROW_STEP = 76
_TEXT = "#edf1f6"
_MUTED = "#9baabd"
_PODIUM = ("#f7d589", "#d0e2f5", "#e9aa84")
_GAME = "原神"
_RANK_LABEL = "命座"
_EQUIPMENT = "武器"
_ACCENT = "#f4be91"
_HEADER = "#30232e"
_STAT_X = (500, 580, 660, 740, 820)
_STAT_LABELS = {"元素充能效率": "充能效率"}


@lru_cache(maxsize=24)
def _font(size: int, name: str = "hywh.ttf"):
    return get_font(size, name)


def _fit(draw: ImageDraw.ImageDraw, text: str, width: int, font) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    end = len(text)
    while end and draw.textlength(text[:end] + "…", font=font) > width:
        end -= 1
    return text[:end] + "…"


def _line(value: object) -> str:
    return " ".join(str(value).split())


def _panel_background(role_name: str) -> Path:
    element = role_info_json.get(role_name, {}).get("元素", "")
    return Path(bg_path) / f"背景_{element}.png"


def _draw_header(
    image: Image.Image, title: str, role_name: str, subtitle: str, count: int
) -> None:
    draw = ImageDraw.Draw(image)
    header_box = (28, 24, 1013, 180)
    header = image.crop(header_box)
    tint = Image.new("RGB", header.size, _HEADER)
    header_mask = Image.new("L", header.size)
    ImageDraw.Draw(header_mask).rounded_rectangle(
        (0, 0, header.width - 1, header.height - 1), radius=22, fill=255
    )
    image.paste(Image.blend(header, tint, 0.48), header_box[:2], header_mask)
    art_path = _PLUGIN_DATA / "res" / "character" / f"{role_name}.png"
    try:
        with Image.open(art_path) as source:
            art = source.convert("RGBA")
        bounds = art.getbbox()
        if bounds:
            art = art.crop(bounds)
            art = ImageOps.fit(
                art, (370, 154), method=Image.Resampling.LANCZOS, centering=(0.5, 0.23)
            )
            fade = Image.linear_gradient("L").rotate(90).resize(art.size)
            art = Image.composite(art, Image.new("RGBA", art.size), fade)
            image.paste(art, (633, 25), art.getchannel("A"))
    except (OSError, ValueError):
        pass
    draw.rectangle((50, 45, 53, 66), fill=_ACCENT)
    draw.text((65, 55), _GAME, font=_font(19), fill=_ACCENT, anchor="lm")
    draw.text(
        (48, 103),
        _fit(draw, _line(title), 630, _font(48, "优设标题黑.ttf")),
        font=_font(48, "优设标题黑.ttf"),
        fill=_TEXT,
        anchor="lm",
    )
    context = f"{count} 位玩家"
    if subtitle:
        context += f"  ·  {subtitle}"
    draw.text(
        (50, 152),
        _fit(draw, context, 590, _font(18)),
        font=_font(18),
        fill=_MUTED,
        anchor="lm",
    )


async def _load_avatar(qq: int) -> Image.Image | None:
    try:
        return await get_img(
            url=f"http://q1.qlogo.cn/g?b=qq&nk={qq}&s=640",
            save_path=_PLUGIN_DATA / "qq_logo" / str(qq),
            size=(50, 50),
            mode="RGBA",
        )
    except Exception:
        # An unavailable QQ avatar should not prevent the board from rendering.
        return None


async def _load_equipment(weapon: Mapping) -> Image.Image | None:
    icon = str(weapon.get("图标") or "")
    if not icon:
        return None
    try:
        star = int(weapon.get("星级") or 0)
    except (TypeError, ValueError, OverflowError):
        star = 0
    star = min(max(star, 1), 5)
    tile = Image.new("RGBA", (50, 50))
    try:
        tile = load_image(f"{other_path}/star{star}.png", size=(50, 50), mode="RGBA")
    except (OSError, ValueError):
        pass
    try:
        icon_image = await get_img(
            url=get_icon_url(icon, str(weapon.get("图标链接") or ""), artifact_url),
            size=(50, 50),
            mode="RGBA",
            save_path=Path(weapon_path) / f"{Path(icon).name}.png",
        )
        tile.alpha_composite(icon_image)
    except Exception:
        pass
    tile.putalpha(
        Image.composite(tile.getchannel("A"), Image.new("L", tile.size), _tile_mask(8))
    )
    return tile


def _tile_mask(radius: int) -> Image.Image:
    mask = Image.new("L", (100, 100))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 99, 99), radius=radius * 2, fill=255)
    return mask.resize((50, 50), Image.Resampling.LANCZOS)


async def draw_role_rank_card(
    title: str,
    role_name: str,
    group_id: int,
    entries: list[RankEntry],
    plugin_version: str,
    metric: str = "评分",
) -> Image.Image:
    if metric not in {"评分", "伤害"}:
        raise ValueError(f"不支持的排行类型: {metric}")
    entries = entries[:16]
    is_damage = metric == "伤害"
    damage_titles = (
        {_line(entry["damage_title"]) for entry in entries if entry.get("damage_title")}
        if is_damage
        else set()
    )
    varied_titles = len(damage_titles) > 1
    subtitle = ""
    if is_damage:
        subtitle = (
            "各玩家伤害项目见名称下方"
            if varied_titles
            else next(iter(damage_titles), "未知项目")
        )

    height = _ROW_START + len(entries) * _ROW_STEP + 52
    image = Image.new("RGB", (_WIDTH, height), "#0b111b")
    try:
        with Image.open(_panel_background(role_name)) as panel_background:
            backdrop = ImageOps.fit(
                panel_background.convert("RGB"),
                image.size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.15),
            )
        image = Image.blend(backdrop, image, 0.57)
    except (OSError, ValueError):
        pass
    _draw_header(image, title, role_name, subtitle, len(entries))
    draw = ImageDraw.Draw(image)
    stat_labels = list(
        dict.fromkeys(label for entry in entries for label, _ in entry["rows"])
    )
    for x, label in zip(_STAT_X, stat_labels):
        draw.text(
            (x, 207),
            _STAT_LABELS.get(label, label),
            font=_font(16),
            fill=_MUTED,
            anchor="mm",
        )
    for x, label in ((62, "名次"), (412, _EQUIPMENT)):
        draw.text((x, 207), label, font=_font(16), fill=_MUTED, anchor="mm")
    draw.text((157, 207), "玩家", font=_font(16), fill=_MUTED, anchor="lm")
    draw.text(
        (986, 207),
        "期望伤害" if is_damage else "评分",
        font=_font(18),
        fill=_ACCENT,
        anchor="rm",
    )

    avatar_mask = _tile_mask(25)
    equipment_icons = {}
    for index, entry in enumerate(entries):
        top = _ROW_START + index * _ROW_STEP
        center = top + 34
        rank_color = _PODIUM[index] if index < len(_PODIUM) else _MUTED
        draw.rounded_rectangle(
            (28, top, 1012, top + 68),
            radius=14,
            fill="#171f2c" if index % 2 == 0 else "#131b27",
        )
        if index < len(_PODIUM):
            draw.rounded_rectangle(
                (29, top + 17, 32, top + 51), radius=2, fill=rank_color
            )
        draw.text(
            (62, center),
            f"{index + 1:02d}",
            font=_font(24, "tahomabd.ttf"),
            fill=rank_color,
            anchor="mm",
        )

        nickname = _line(entry.get("nickname") or entry["qq"])
        avatar = await _load_avatar(entry["qq"])
        if avatar is not None:
            image.paste(avatar, (95, top + 9), avatar_mask)
        else:
            draw.ellipse((95, top + 9, 144, top + 58), fill=_HEADER)
            draw.text(
                (120, center), nickname[:1], fill=_ACCENT, font=_font(22), anchor="mm"
            )
        draw.text(
            (157, center - 12),
            _fit(draw, nickname, 220, _font(24)),
            fill=_TEXT,
            font=_font(24),
            anchor="lm",
        )
        detail = f"{_RANK_LABEL} {entry.get('rank', 0)}"
        if varied_titles and entry.get("damage_title"):
            detail += f"  ·  {_line(entry['damage_title'])}"
        draw.text(
            (157, center + 15),
            _fit(draw, detail, 220, _font(16)),
            fill=_MUTED,
            font=_font(16),
            anchor="lm",
        )

        weapon = entry.get("weapon") or {}
        refinement = str(weapon.get("精炼等级", ""))
        show_refinement = is_damage and refinement in {"1", "2", "3", "4", "5"}
        equipment_y = center - 7 if show_refinement else center
        key = (weapon.get("图标"), weapon.get("星级"), weapon.get("图标链接"))
        if key not in equipment_icons:
            equipment_icons[key] = await _load_equipment(weapon)
        icon = equipment_icons[key]
        if icon is not None:
            image.paste(icon, (387, equipment_y - 25), icon.getchannel("A"))
        else:
            draw.text((412, equipment_y), "—", font=_font(20), fill=_MUTED, anchor="mm")
        if show_refinement:
            draw.text(
                (412, top + 60),
                f"精炼 {refinement} 阶",
                font=_font(15),
                fill=_ACCENT,
                anchor="mm",
            )

        stats = dict(entry["rows"])
        for x, label in zip(_STAT_X, stat_labels):
            number = str(stats.get(label, "—"))
            font = _font(18, "tahomabd.ttf")
            if draw.textlength(number, font=font) > 77:
                font = _font(15, "tahomabd.ttf")
            draw.text(
                (x, center),
                _fit(draw, number, 77, font),
                fill=_TEXT,
                font=font,
                anchor="mm",
            )

        draw.line((874, top + 17, 874, top + 51), fill="#303d50")
        value = float(entry["value"])
        value_text = f"{value:,.0f}" if is_damage else f"{value:,.1f}"
        value_font = _font(28, "tahomabd.ttf")
        while (
            value_font.size > 12 and draw.textlength(value_text, font=value_font) > 104
        ):
            value_font = _font(value_font.size - 1, "tahomabd.ttf")
        draw.text(
            (986, center),
            _fit(draw, value_text, 104, value_font),
            fill=_ACCENT,
            font=value_font,
            anchor="rm",
        )

    footer_y = height - 30
    draw.line((29, footer_y - 14, 1011, footer_y - 14), fill="#283442")
    draw.text(
        (29, footer_y + 3), f"群 {group_id}", font=_font(15), fill=_MUTED, anchor="lm"
    )
    draw.text(
        (1011, footer_y + 3),
        f"v{plugin_version}",
        font=_font(15),
        fill=_MUTED,
        anchor="rm",
    )
    return image
