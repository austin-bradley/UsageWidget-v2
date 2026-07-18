from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from core.models import AppSnapshot, DisplayProfile, DisplaySlot, Metric
from display.format_value import format_slot, resolve_metric


RGBA = tuple[int, int, int, int]
ResolvedSlot = tuple[DisplaySlot, Metric]

_BACKGROUND: RGBA = (30, 30, 30, 255)
_TRACK: RGBA = (58, 58, 58, 255)
_MUTED: RGBA = (140, 140, 140, 255)
_TEXT: RGBA = (238, 238, 238, 255)


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _color_for_pct(pct: int | None, thresholds: dict[str, int]) -> RGBA:
    if pct is None:
        return _MUTED
    if pct >= thresholds.get("critical", 85):
        return (224, 90, 90, 255)
    if pct >= thresholds.get("warn", 60):
        return (224, 180, 70, 255)
    return (110, 200, 120, 255)


def _resolved_slots(profile: DisplayProfile, snapshot: AppSnapshot) -> list[ResolvedSlot]:
    resolved: list[ResolvedSlot] = []
    for slot in profile.icon.slots[: max(0, profile.icon.max_slots)]:
        match = resolve_metric(snapshot, slot.ref)
        if match is not None:
            _, metric = match
            resolved.append((slot, metric))
    return resolved


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int, tuple[int, int, int, int]]:
    bounds = draw.textbbox((0, 0), text, font=font)
    return bounds[2] - bounds[0], bounds[3] - bounds[1], bounds


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    start_size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for size in range(start_size, 7, -1):
        font = _find_font(size)
        width, height, _ = _text_size(draw, text, font)
        if width <= max_width and height <= max_height:
            return font
    return _find_font(8)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    color: RGBA,
    start_size: int,
) -> None:
    left, top, right, bottom = box
    font = _fit_font(
        draw,
        text,
        max_width=max(1, right - left - 4),
        max_height=max(1, bottom - top - 4),
        start_size=start_size,
    )
    width, height, bounds = _text_size(draw, text, font)
    x = left + (right - left - width) / 2 - bounds[0]
    y = top + (bottom - top - height) / 2 - bounds[1]
    draw.text((x, y), text, font=font, fill=color)


def _draw_value(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    item: ResolvedSlot,
    profile: DisplayProfile,
    start_size: int,
) -> None:
    slot, metric = item
    color = _color_for_pct(metric.used_pct, profile.icon.thresholds)
    value_top = box[1]
    if profile.icon.show_labels:
        label = slot.label or metric.label
        label_box = (box[0], box[1] + 2, box[2], box[1] + 16)
        _draw_centered_text(draw, label_box, label, _TEXT, 11)
        value_top = box[1] + 14
    _draw_centered_text(
        draw,
        (box[0], value_top, box[2], box[3]),
        format_slot(slot, metric),
        color,
        start_size,
    )


def _draw_split(
    draw: ImageDraw.ImageDraw,
    items: Sequence[ResolvedSlot],
    profile: DisplayProfile,
) -> None:
    visible = list(items[:2])
    if len(visible) == 1:
        _draw_value(draw, (3, 3, 61, 61), visible[0], profile, 38)
        return
    draw.line((32, 7, 32, 57), fill=(76, 76, 76, 255), width=1)
    _draw_value(draw, (3, 3, 32, 61), visible[0], profile, 24)
    _draw_value(draw, (33, 3, 61, 61), visible[1], profile, 24)


def _draw_stacked_bars(
    draw: ImageDraw.ImageDraw,
    items: Sequence[ResolvedSlot],
    profile: DisplayProfile,
) -> None:
    visible = list(items[:3])
    row_height = 54 // len(visible)
    font = _find_font(min(11, max(8, row_height - 6)))
    for index, (slot, metric) in enumerate(visible):
        top = 5 + index * row_height
        bottom = min(59, top + row_height - 4)
        draw.rounded_rectangle((5, top, 59, bottom), radius=4, fill=_TRACK)
        pct = metric.used_pct
        if pct is not None:
            fill_right = 5 + round(54 * max(0, min(100, pct)) / 100)
            if fill_right > 5:
                draw.rounded_rectangle(
                    (5, top, fill_right, bottom),
                    radius=4,
                    fill=_color_for_pct(pct, profile.icon.thresholds),
                )
        value = format_slot(slot, metric)
        prefix = f"{slot.label or metric.label} " if profile.icon.show_labels else ""
        text = f"{prefix}{value}"
        bounds = draw.textbbox((0, 0), text, font=font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        draw.text(
            (
                32 - text_width / 2 - bounds[0],
                top + (bottom - top - text_height) / 2 - bounds[1],
            ),
            text,
            font=font,
            fill=_TEXT,
        )


def render_icon(
    profile: DisplayProfile,
    snapshot: AppSnapshot,
    rotate_index: int = 0,
) -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=_BACKGROUND)

    items = _resolved_slots(profile, snapshot)
    if not items:
        _draw_centered_text(draw, (3, 3, 61, 61), "?", _MUTED, 40)
        return image

    if profile.icon.mode == "rotate":
        selected = items[rotate_index % len(items)]
        _draw_value(draw, (3, 3, 61, 61), selected, profile, 38)
    elif profile.icon.mode == "single" or profile.icon.layout == "primary_only":
        _draw_value(draw, (3, 3, 61, 61), items[0], profile, 38)
    elif profile.icon.mode == "composite" and profile.icon.layout == "stacked_bars":
        _draw_stacked_bars(draw, items, profile)
    else:
        _draw_split(draw, items, profile)
    return image
