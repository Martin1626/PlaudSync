"""4-state tray icon generator (programmatic PIL Image, žádné bundle PNG v v0).

Design: rounded-square background (state color) + bílý glyph uprostřed.

Stavy:
- idle    = modrá  + sync-arrows  (cloud sync motiv)
- running = modrá  + sync-arrows + žlutý "puls" v rohu
- error   = červená + vykřičník
- paused  = šedá   + pause bars (||)

Ikona: 64×64 RGBA PNG.
"""
from __future__ import annotations

from typing import Literal

from PIL import Image, ImageDraw

IconState = Literal["idle", "running", "error", "paused"]

_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (25, 118, 210),
    "running": (25, 118, 210),
    "error": (211, 47, 47),
    "paused": (97, 97, 97),
}
_PULSE_COLOR = (255, 213, 79)
_GLYPH = (255, 255, 255)
_SIZE = 64
_RADIUS = 14  # rounded-square corner radius


def _rounded_square(draw: ImageDraw.ImageDraw, color: tuple[int, int, int]) -> None:
    """Background — rounded square s lehkým padded okrajem."""
    draw.rounded_rectangle((4, 4, _SIZE - 4, _SIZE - 4), radius=_RADIUS, fill=color + (255,))


def _draw_sync_arrows(draw: ImageDraw.ImageDraw) -> None:
    """Dva půlkruhové oblouky se šipkami (clockwise + counter-clockwise) — sync motiv."""
    # Outer arc top-right (clockwise arrow heading down-right)
    draw.arc((16, 16, 48, 48), start=200, end=20, fill=_GLYPH + (255,), width=4)
    # Outer arc bottom-left (clockwise heading up-left)
    draw.arc((16, 16, 48, 48), start=20, end=200, fill=None, width=0)  # second arc invisible to keep symmetry
    draw.arc((16, 16, 48, 48), start=20, end=200, fill=_GLYPH + (255,), width=4)
    # Arrow head 1 (top-right end of first arc)
    draw.polygon([(46, 18), (52, 22), (44, 26)], fill=_GLYPH + (255,))
    # Arrow head 2 (bottom-left end of second arc)
    draw.polygon([(18, 46), (12, 42), (20, 38)], fill=_GLYPH + (255,))


def _draw_pause(draw: ImageDraw.ImageDraw) -> None:
    """Dva svislé pruhy pro pause."""
    draw.rounded_rectangle((22, 18, 28, 46), radius=2, fill=_GLYPH + (255,))
    draw.rounded_rectangle((36, 18, 42, 46), radius=2, fill=_GLYPH + (255,))


def _draw_exclamation(draw: ImageDraw.ImageDraw) -> None:
    """Vykřičník pro error."""
    draw.rounded_rectangle((29, 16, 35, 40), radius=2, fill=_GLYPH + (255,))
    draw.ellipse((28, 44, 36, 52), fill=_GLYPH + (255,))


def _draw_pulse_dot(draw: ImageDraw.ImageDraw) -> None:
    """Žlutý puls v pravém dolním rohu — 'right now syncing' indikátor."""
    draw.ellipse((42, 42, 56, 56), fill=_PULSE_COLOR + (255,))
    # Slight white border for contrast against blue bg
    draw.ellipse((42, 42, 56, 56), outline=(255, 255, 255, 200), width=1)


def make_icon_image(state: str) -> Image.Image:
    color = _COLORS.get(state, _COLORS["idle"])
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    _rounded_square(draw, color)

    if state == "error":
        _draw_exclamation(draw)
    elif state == "paused":
        _draw_pause(draw)
    else:
        _draw_sync_arrows(draw)
        if state == "running":
            _draw_pulse_dot(draw)

    return img
