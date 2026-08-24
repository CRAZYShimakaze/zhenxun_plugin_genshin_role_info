from __future__ import annotations

from PIL import Image, ImageDraw

from ..utils.card_utils import bg_path, get_font, other_path, weapon_path
from ..utils.image_utils import draw_center_text, draw_right_text, get_img, load_image
from ..utils.rank_utils import RankEntry
from .draw_artifact_card import (
    artifact_url,
    draw_qq_logo_mask,
    get_icon_url,
    role_info_json,
)


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    preferred: int,
    minimum: int = 18,
    font_name: str = "hywh.ttf",
):
    for size in range(preferred, minimum - 1, -2):
        font = get_font(size, font_name)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return get_font(minimum, font_name)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    preferred: int,
    minimum: int = 18,
    font_name: str = "hywh.ttf",
) -> tuple[str, object]:
    font = _fit_font(
        draw,
        text,
        max_width,
        preferred,
        minimum=minimum,
        font_name=font_name,
    )
    if draw.textlength(text, font=font) <= max_width:
        return text, font

    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return text + suffix, font


async def draw_role_rank_card(
    title: str,
    role_name: str,
    group_id: int,
    entries: list[RankEntry],
    plugin_version: str,
    metric: str,
) -> Image.Image:
    boundary = (70, 130)
    interval_y = 15
    mask_bottom = load_image(path=f"{other_path}/底遮罩.png", crop=(707, 936, 1024, 1370))
    mask_w, mask_h = mask_bottom.size
    rows = (len(entries) + 3) // 4
    width = boundary[0] * 2 + mask_w * 4
    height = (
        boundary[1] * 2
        + mask_h * rows
        + interval_y * (rows - 1)
        - 50
    )
    element = role_info_json[role_name]["元素"]
    background = load_image(f"{bg_path}/背景_{element}.png", size=(width, height), mode="RGBA")
    draw = ImageDraw.Draw(background)
    weapon_backgrounds: dict[int, Image.Image] = {}
    weapon_icons: dict[tuple[str, str], Image.Image] = {}

    for index, entry in enumerate(entries):
        x = boundary[0] + mask_w * (index % 4)
        y = boundary[1] + (mask_h + interval_y) * (index // 4)
        background.alpha_composite(mask_bottom, (x, y))
        try:
            avatar = await draw_qq_logo_mask({"QQ": entry["qq"]}, mask_bottom)
            background.alpha_composite(avatar, (x, y))
        except Exception:
            pass

        rank_text = f"#{index + 1}"
        draw_right_text(
            draw,
            rank_text,
            x + mask_w - 18,
            y + 18,
            "#ffde6b",
            get_font(28, "number.ttf"),
        )
        nickname = str(entry["nickname"])
        nickname, nickname_font = _fit_text(draw, nickname, mask_w - 105, 38, minimum=16)
        draw.text(
            (x + 24, y + 16),
            nickname,
            fill="white",
            font=nickname_font,
        )

        value = float(entry["value"])
        metric_font = get_font(28)
        draw.text(
            (x + 24, y + 63),
            metric,
            fill="#ffde6b",
            font=metric_font,
        )
        value_text = f"{value:,.1f}" if metric == "评分" else f"{value:,.0f}"
        value_x = x + 36 + draw.textlength(metric, font=metric_font)
        draw.text(
            (value_x, y + 63),
            value_text,
            fill="#ffde6b",
            font=_fit_font(
                draw,
                value_text,
                x + 194 - value_x,
                30,
                minimum=18,
                font_name="number.ttf",
            ),
        )
        weapon = entry.get("weapon", {})
        try:
            weapon_star = int(weapon.get("星级", 1) or 1)
        except (TypeError, ValueError):
            weapon_star = 1
        if weapon_star not in weapon_backgrounds:
            weapon_backgrounds[weapon_star] = load_image(f"{other_path}/star{weapon_star}.png", size=(100, 100))
        background.alpha_composite(
            weapon_backgrounds[weapon_star],
            (x + 200, y + 67),
        )
        weapon_icon_name = str(weapon.get("图标", ""))
        weapon_icon_source = str(weapon.get("图标链接", ""))
        if weapon_icon_name:
            cache_key = weapon_icon_name, weapon_icon_source
            if cache_key not in weapon_icons:
                try:
                    weapon_icons[cache_key] = await get_img(
                        url=get_icon_url(
                            weapon_icon_name,
                            weapon_icon_source,
                            artifact_url,
                        ),
                        size=(100, 100),
                        save_path=f"{weapon_path}/{weapon_icon_name}.png",
                        mode="RGBA",
                    )
                except Exception:
                    pass
            if weapon_icon := weapon_icons.get(cache_key):
                background.alpha_composite(
                    weapon_icon,
                    (x + 200, y + 67),
                )

        level_mask = load_image(path=f"{other_path}/等级遮罩.png")
        background.alpha_composite(level_mask.resize((98, 30)), (x + 24, y + 112))
        draw_center_text(
            draw,
            f"命座{entry['rank']}",
            x + 24,
            x + 122,
            y + 113,
            "black",
            get_font(27),
        )

        for row_index, (label, row_value) in enumerate(entry["rows"]):
            row_y = y + 183 + row_index * 52
            label = str(label)
            row_value = str(row_value)
            draw.text(
                (x + 24, row_y),
                label,
                fill="#dfdfdf",
                font=_fit_font(draw, label, 120, 25),
            )
            draw_right_text(
                draw,
                row_value,
                x + mask_w - 24,
                row_y,
                "white",
                _fit_font(draw, row_value, 155, 25, minimum=16),
            )

    draw_center_text(draw, title, 0, width, 5, "white", get_font(96, "优设标题黑.ttf"))
    if metric == "伤害":
        damage_titles = list(
            dict.fromkeys(
                str(entry["damage_title"])
                for entry in entries
                if entry.get("damage_title")
            )
        )
        footer = (
            f"group:{group_id}丨{'/'.join(damage_titles) or '未知项目'}丨 "
            f"v{plugin_version}"
        )
    else:
        footer = f"group:{group_id} | v{plugin_version}"
    footer, footer_font = _fit_text(
        draw,
        footer,
        width - 100,
        46,
        minimum=24,
        font_name="优设标题黑.ttf",
    )
    draw_center_text(
        draw,
        footer,
        0,
        width,
        height - 70,
        "white",
        footer_font,
    )
    return background.convert("RGB")
