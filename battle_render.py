"""Static HTML and PNG rendering for Genshin battle records."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import tempfile
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

_PLUGIN_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _PLUGIN_DIR / "templates"
_CACHE_DIR = _PLUGIN_DIR / "user_data" / "res" / "battle_icons"
_FONT_PATH = _PLUGIN_DIR / "res" / "fonts" / "hywh.ttf"
_ALLOWED_IMAGE_DOMAINS = (
    "mihoyo.com",
    "miyoushe.com",
    "hoyoverse.com",
    "hoyolab.com",
    "enka.network",
)
_IMAGE_DATA_RE = re.compile(
    r"^data:image/(?:png|jpeg|webp|gif);base64,([A-Za-z0-9+/]*={0,2})$"
)
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_PIXELS = 4_000_000
_MAX_REDIRECTS = 3
_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(("html",)),
)


def _sequence(value: object) -> list:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _display(value: object, fallback: str = "") -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    return fallback


def _integer(value: object, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return min(maximum, max(minimum, number))


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _trusted_image_url(value: object) -> bool:
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return False
    return any(
        host == domain or host.endswith("." + domain)
        for domain in _ALLOWED_IMAGE_DOMAINS
    )


def _data_image(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > (_MAX_DOWNLOAD_BYTES * 4 // 3 + 128):
        return None
    match = _IMAGE_DATA_RE.fullmatch(value)
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    if not raw or len(raw) > _MAX_DOWNLOAD_BYTES:
        return None
    return value


def _iter_image_urls(report: object) -> set[str]:
    data = _mapping(report)
    found: set[str] = set()

    def collect_avatar(value: object) -> None:
        icon = _mapping(value).get("icon")
        if _trusted_image_url(icon):
            found.add(icon)

    for floor in _sequence(data.get("floors")):
        for chamber in _sequence(_mapping(floor).get("chambers")):
            for team in _sequence(_mapping(chamber).get("teams")):
                for avatar in _sequence(_mapping(team).get("avatars")):
                    collect_avatar(avatar)
    for act in _sequence(data.get("acts")):
        for avatar in _sequence(_mapping(act).get("avatars")):
            collect_avatar(avatar)
    for challenge in _sequence(data.get("challenges")):
        for boss in _sequence(_mapping(challenge).get("bosses")):
            boss_icon = _mapping(boss).get("icon")
            if _trusted_image_url(boss_icon):
                found.add(boss_icon)
            for avatar in _sequence(_mapping(boss).get("avatars")):
                collect_avatar(avatar)
    return found


def _cached_image_path(url: str) -> Path:
    name = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{name}.png"


def _read_cached_image(path: Path) -> bytes | None:
    try:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > _MAX_DOWNLOAD_BYTES
        ):
            return None
        return path.read_bytes()
    except OSError:
        return None


def _write_cached_image(path: Path, content: bytes) -> None:
    temp_name = None
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=_CACHE_DIR,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(content)
        Path(temp_name).replace(path)
    except OSError:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _normalize_image(content: bytes) -> bytes | None:
    if not content or len(content) > _MAX_DOWNLOAD_BYTES:
        return None
    try:
        from PIL import Image

        with Image.open(BytesIO(content)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                return None
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
                return None
            source.seek(0)
            has_alpha = (
                "A" in source.getbands() or source.info.get("transparency") is not None
            )
            source.thumbnail((256, 256), Image.Resampling.LANCZOS)
            image = source.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            normalized = output.getvalue()
            return normalized if len(normalized) <= _MAX_DOWNLOAD_BYTES else None
    except Exception:
        return None


async def _fetch_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    current_url = url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        if not _trusted_image_url(current_url):
            return None
        try:
            async with client.stream(
                "GET", current_url, follow_redirects=False
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count >= _MAX_REDIRECTS:
                        return None
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if (
                    content_type
                    and not content_type.lower().startswith("image/")
                    and content_type.lower() != "application/octet-stream"
                ):
                    return None
                length = response.headers.get("content-length")
                if length and int(length) > _MAX_DOWNLOAD_BYTES:
                    return None
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > _MAX_DOWNLOAD_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except (httpx.HTTPError, ValueError):
            return None
    return None


async def _load_image_data_uri(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: str
) -> str | None:
    path = _cached_image_path(url)
    cached = await asyncio.to_thread(_read_cached_image, path)
    if cached is not None:
        normalized = await asyncio.to_thread(_normalize_image, cached)
        if normalized is not None:
            return "data:image/png;base64," + base64.b64encode(normalized).decode(
                "ascii"
            )

    async with semaphore:
        downloaded = await _fetch_image(client, url)
    if downloaded is None:
        return None
    normalized = await asyncio.to_thread(_normalize_image, downloaded)
    if normalized is None:
        return None
    await asyncio.to_thread(_write_cached_image, path, normalized)
    return "data:image/png;base64," + base64.b64encode(normalized).decode("ascii")


async def _download_images(urls: set[str]) -> dict[str, str]:
    if not urls:
        return {}
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    timeout = httpx.Timeout(12.0, connect=5.0)
    semaphore = asyncio.Semaphore(8)
    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": "Zhenxun-Genshin-Battle-Renderer/1.0"},
    ) as client:
        results = await asyncio.gather(
            *(_load_image_data_uri(client, semaphore, url) for url in urls),
            return_exceptions=True,
        )
    return {
        url: result for url, result in zip(urls, results) if isinstance(result, str)
    }


def _resolve_icon(value: object, images: Mapping[str, str] | None) -> str | None:
    if isinstance(value, str) and images and value in images:
        return images[value]
    return _data_image(value)


def _clean_avatar(value: object, images: Mapping[str, str] | None) -> dict:
    avatar = _mapping(value)
    return {
        "id": _display(avatar.get("id")),
        "name": _display(avatar.get("name"), "未知角色"),
        "icon": _resolve_icon(avatar.get("icon"), images),
        "element": _display(avatar.get("element")),
        "level": _integer(avatar.get("level"), 1, 100),
        "rarity": _integer(avatar.get("rarity"), 1, 5),
    }


def _clean_team(value: object, images: Mapping[str, str] | None) -> dict:
    team = _mapping(value)
    return {
        "label": _display(team.get("label")),
        "avatars": [
            _clean_avatar(avatar, images) for avatar in _sequence(team.get("avatars"))
        ],
    }


def _clean_report(value: object, images: Mapping[str, str] | None = None) -> dict:
    source = _mapping(value)
    kind = _display(source.get("kind"))
    if kind not in {"abyss", "theater", "stygian"}:
        kind = ""

    floors = []
    for raw_floor in _sequence(source.get("floors")):
        floor = _mapping(raw_floor)
        chambers = []
        for raw_chamber in _sequence(floor.get("chambers")):
            chamber = _mapping(raw_chamber)
            chambers.append(
                {
                    "index": _display(chamber.get("index"), "—"),
                    "star": _integer(chamber.get("star"), 0, 3),
                    "max_star": _integer(chamber.get("max_star"), 0, 3),
                    "teams": [
                        _clean_team(team, images)
                        for team in _sequence(chamber.get("teams"))
                    ],
                }
            )
        floors.append(
            {
                "index": _display(floor.get("index"), "—"),
                "star": _integer(floor.get("star"), 0, 9),
                "max_star": _integer(floor.get("max_star"), 0, 9),
                "chambers": chambers,
            }
        )

    acts = []
    for raw_act in _sequence(source.get("acts")):
        act = _mapping(raw_act)
        acts.append(
            {
                "label": _display(act.get("label")),
                "medal": act.get("medal") is True,
                "avatars": [
                    _clean_avatar(avatar, images)
                    for avatar in _sequence(act.get("avatars"))
                ],
            }
        )

    challenges = []
    for raw_challenge in _sequence(source.get("challenges")):
        challenge = _mapping(raw_challenge)
        bosses = []
        for raw_boss in _sequence(challenge.get("bosses")):
            boss = _mapping(raw_boss)
            bosses.append(
                {
                    "name": _display(boss.get("name"), "未知首领"),
                    "icon": _resolve_icon(boss.get("icon"), images),
                    "second": _display(boss.get("second")),
                    "avatars": [
                        _clean_avatar(avatar, images)
                        for avatar in _sequence(boss.get("avatars"))
                    ],
                }
            )
        challenges.append(
            {
                "label": _display(challenge.get("label"), "挑战记录"),
                "summary": _display(challenge.get("summary")),
                "bosses": bosses,
            }
        )

    hero_source = _mapping(source.get("hero"))
    hero = {
        "label": _display(hero_source.get("label")),
        "value": _display(hero_source.get("value")),
        "unit": _display(hero_source.get("unit")),
        "note": _display(hero_source.get("note")),
    }
    metrics = []
    for item in _sequence(source.get("metrics")):
        if not isinstance(item, Mapping):
            continue
        metric = {
            "label": _display(item.get("label")),
            "value": _display(item.get("value")),
        }
        if metric["label"] or metric["value"]:
            metrics.append(metric)
    highlights = [
        {
            "label": _display(_mapping(item).get("label")),
            "value": _display(_mapping(item).get("value")),
            "note": _display(_mapping(item).get("note")),
        }
        for item in _sequence(source.get("highlights"))
        if isinstance(item, Mapping)
        and (
            _display(item.get("label"))
            or _display(item.get("value"))
            or _display(item.get("note"))
        )
    ]
    return {
        "kind": kind,
        "title": _display(source.get("title"), "原神挑战战绩"),
        "eyebrow": _display(source.get("eyebrow")),
        "period_label": _display(source.get("period_label")),
        "date_range": _display(source.get("date_range")),
        "uid": _display(source.get("uid")),
        "nickname": _display(source.get("nickname"), "旅行者"),
        "hero": hero,
        "metrics": metrics,
        "floors": floors,
        "acts": acts,
        "challenges": challenges,
        "highlights": highlights,
        "notes": [
            note for note in _sequence(source.get("notes")) if isinstance(note, str)
        ],
        "empty_message": _display(source.get("empty_message")),
    }


def _render_clean_report(report: dict) -> str:
    template = _TEMPLATE_ENV.get_template("battle_records.html")
    return template.render(
        report=report,
        font_uri=_FONT_PATH.as_uri(),
        static_base=_TEMPLATE_DIR.resolve().as_uri() + "/",
    )


def render_battle_html(report: dict) -> str:
    """Render a safe, static HTML document from normalized battle data."""
    return _render_clean_report(_clean_report(report))


async def render_battle_report(report: dict) -> bytes:
    """Download permitted icon images and render the report as a PNG."""
    images = await _download_images(_iter_image_urls(report))
    html = _render_clean_report(_clean_report(report, images))
    return await render_report_image(html)


async def render_report_image(html: str, *, width: int = 720) -> bytes:
    """使用战绩面板共用的尺寸、字体和截图设置。"""

    from nonebot import require

    require("nonebot_plugin_htmlrender")
    from nonebot_plugin_htmlrender import html_to_pic

    return await html_to_pic(
        html=html,
        template_path=_TEMPLATE_DIR.resolve().as_uri() + "/",
        type="png",
        device_scale_factor=2,
        viewport={"width": width, "height": 10},
        screenshot_timeout=30_000,
    )
