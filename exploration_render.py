"""按旧版 ys 玩家卡的分区渲染总览、洞天与探索信息。"""

from __future__ import annotations

import base64
from copy import deepcopy

from .battle_render import (
    _FONT_PATH,
    _PLUGIN_DIR,
    _TEMPLATE_DIR,
    _TEMPLATE_ENV,
    _download_images,
    _normalize_image,
    _read_cached_image,
    _resolve_icon,
    _trusted_image_url,
    render_report_image,
)
from .exploration import REGION_ORDER


def _image_items(report: dict) -> list[dict]:
    return [*report.get("regions", []), *report.get("homes", {}).get("realms", [])]


def _local_region_icon(name: str) -> str | None:
    """优先使用随插件提供的地区纹章，避免接口图片缺失或配色不可见。"""
    if name not in REGION_ORDER:
        return None
    content = _read_cached_image(_PLUGIN_DIR / "res" / "region" / f"{name}.png")
    if content is None:
        return None
    normalized = _normalize_image(content)
    if normalized is None:
        return None
    return "data:image/png;base64," + base64.b64encode(normalized).decode("ascii")


def render_exploration_html(report: dict, images: dict[str, str] | None = None) -> str:
    """使用模板自动转义文本；图像仅允许已处理的数据 URI。"""
    clean = deepcopy(report)
    for item in clean.get("regions", []):
        item["icon"] = _local_region_icon(item.get("name", "")) or _resolve_icon(
            item.get("icon"), images
        )
    for item in clean.get("homes", {}).get("realms", []):
        item["icon"] = _resolve_icon(item.get("icon"), images)
    return _TEMPLATE_ENV.get_template("exploration.html").render(
        report=clean,
        font_uri=_FONT_PATH.as_uri(),
        static_base=_TEMPLATE_DIR.resolve().as_uri() + "/",
    )


async def render_exploration_report(report: dict) -> bytes:
    remote_items = [
        item
        for item in report.get("regions", [])
        if _local_region_icon(item.get("name", "")) is None
    ] + report.get("homes", {}).get("realms", [])
    urls = {
        item["icon"] for item in remote_items if _trusted_image_url(item.get("icon"))
    }
    images = await _download_images(urls)
    return await render_report_image(
        render_exploration_html(report, images), width=1000
    )
