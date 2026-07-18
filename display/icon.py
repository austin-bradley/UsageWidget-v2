from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from core.models import AppSnapshot, DisplayProfile, DisplaySlot, Metric
from display.format_value import format_slot, resolve_metric


RGBA = tuple[int, int, int, int]
ResolvedSlot = tuple[DisplaySlot, Metric]

_BACKGROUND: RGBA = (28, 28, 30, 255)
_TRACK: RGBA = (52, 52, 56, 255)
_MUTED: RGBA = (142, 142, 147, 255)
_TEXT: RGBA = (245, 245, 247, 255)
_DIVIDER: RGBA = (72, 72, 76, 255)


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\seguisb.ttf",
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
        return (255, 99, 97, 255)
    if pct >= thresholds.get("warn", 60):
        return (255, 199, 87, 255)
    return (52, 199, 89, 255)


def _color_for_metric(
    metric: Metric,
    color_by: str,
    thresholds: dict[str, int],
) -> RGBA:
    if color_by == "none":
        return _TEXT
    pct = metric.used_pct
    if pct is None:
        return _MUTED
    return _color_for_pct(pct, thresholds)


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


def _draw_status_ring(
    draw: ImageDraw.ImageDraw,
    color: RGBA,
    *,
    inset: int = 3,
) -> None:
    # Soft outer ring so single-digit icons still read as "metered".
    ring = (*color[:3], 210)
    draw.rounded_rectangle(
        (inset, inset, 64 - inset, 64 - inset),
        radius=13,
        outline=ring,
        width=2,
    )


def _draw_value(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    item: ResolvedSlot,
    profile: DisplayProfile,
    start_size: int,
) -> None:
    slot, metric = item
    color = _color_for_metric(metric, profile.icon.color_by, profile.icon.thresholds)
    value_top = box[1]
    if profile.icon.show_labels:
        label = (slot.label or metric.label)[:3]
        label_box = (box[0], box[1] + 1, box[2], box[1] + 14)
        _draw_centered_text(draw, label_box, label, _MUTED, 10)
        value_top = box[1] + 12
    _draw_centered_text(
        draw,
        (box[0], value_top, box[2], box[3]),
        format_slot(slot, metric, compact=True),
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
        color = _color_for_metric(
            visible[0][1], profile.icon.color_by, profile.icon.thresholds
        )
        _draw_status_ring(draw, color)
        _draw_value(draw, (4, 4, 60, 60), visible[0], profile, 36)
        return
    draw.line((32, 10, 32, 54), fill=_DIVIDER, width=1)
    _draw_value(draw, (4, 4, 31, 60), visible[0], profile, 22)
    _draw_value(draw, (33, 4, 60, 60), visible[1], profile, 22)


def _draw_stacked_bars(
    draw: ImageDraw.ImageDraw,
    items: Sequence[ResolvedSlot],
    profile: DisplayProfile,
) -> None:
    visible = list(items[:3])
    row_height = 52 // len(visible)
    font = _find_font(min(11, max(8, row_height - 6)))
    for index, (slot, metric) in enumerate(visible):
        top = 6 + index * row_height
        bottom = min(58, top + row_height - 4)
        draw.rounded_rectangle((6, top, 58, bottom), radius=5, fill=_TRACK)
        pct = metric.used_pct
        if pct is not None:
            fill_right = 6 + round(52 * max(0, min(100, pct)) / 100)
            if fill_right > 6:
                draw.rounded_rectangle(
                    (6, top, fill_right, bottom),
                    radius=5,
                    fill=_color_for_pct(pct, profile.icon.thresholds),
                )
        value = format_slot(slot, metric, compact=True)
        prefix = f"{(slot.label or metric.label)[:3]} " if profile.icon.show_labels else ""
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


def _draw_badge_grid(
    draw: ImageDraw.ImageDraw,
    items: Sequence[ResolvedSlot],
    profile: DisplayProfile,
) -> None:
    visible = list(items[:4])
    if len(visible) == 3:
        _draw_value(draw, (4, 4, 30, 30), visible[0], profile, 15)
        _draw_value(draw, (34, 4, 60, 30), visible[1], profile, 15)
        _draw_value(draw, (4, 34, 60, 60), visible[2], profile, 16)
        draw.line((32, 6, 32, 28), fill=_DIVIDER, width=1)
        draw.line((6, 32, 58, 32), fill=_DIVIDER, width=1)
        return
    boxes = ((4, 4, 30, 30), (34, 4, 60, 30), (4, 34, 30, 60), (34, 34, 60, 60))
    for index, item in enumerate(visible):
        _draw_value(draw, boxes[index], item, profile, 15)
    if len(visible) >= 2:
        draw.line((32, 6, 32, 58), fill=_DIVIDER, width=1)
    if len(visible) >= 3:
        draw.line((6, 32, 58, 32), fill=_DIVIDER, width=1)


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
        has_error = any(account.error for account in snapshot.accounts)
        color = (255, 99, 97, 255) if has_error else _MUTED
        _draw_status_ring(draw, color)
        _draw_centered_text(
            draw,
            (4, 4, 60, 60),
            "!" if has_error else "·",
            color,
            40,
        )
        return image

    if profile.icon.mode == "rotate":
        selected = items[rotate_index % len(items)]
        color = _color_for_metric(
            selected[1], profile.icon.color_by, profile.icon.thresholds
        )
        _draw_status_ring(draw, color)
        _draw_value(draw, (4, 4, 60, 60), selected, profile, 36)
    elif profile.icon.mode == "single" or profile.icon.layout == "primary_only":
        color = _color_for_metric(
            items[0][1], profile.icon.color_by, profile.icon.thresholds
        )
        _draw_status_ring(draw, color)
        _draw_value(draw, (4, 4, 60, 60), items[0], profile, 36)
    elif profile.icon.mode == "composite" and profile.icon.layout == "stacked_bars":
        _draw_stacked_bars(draw, items, profile)
    elif profile.icon.mode == "composite" and profile.icon.layout == "badge_grid":
        _draw_badge_grid(draw, items, profile)
    else:
        _draw_split(draw, items, profile)
    return image
