"""4-state tray icon generator (programmatic PIL Image, žádné bundle PNG v v0).

Stav → barva (RGB):
- idle    = modrá (#1976D2)
- running = modrá s žlutou tečkou uprostřed (#FBC02D)
- error   = červená (#D32F2F)
- paused  = šedá (#757575)

Ikona: 64×64 PNG circle.
"""
from __future__ import annotations

from typing import Literal

from PIL import Image, ImageDraw

IconState = Literal["idle", "running", "error", "paused"]

_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (25, 118, 210),
    "running": (25, 118, 210),
    "error": (211, 47, 47),
    "paused": (117, 117, 117),
}
_DOT_COLOR = (251, 192, 45)
_SIZE = 64


def make_icon_image(state: str) -> Image.Image:
    color = _COLORS.get(state, _COLORS["idle"])
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, _SIZE - 4, _SIZE - 4), fill=color + (255,))
    if state == "running":
        draw.ellipse((24, 24, 40, 40), fill=_DOT_COLOR + (255,))
    return img
