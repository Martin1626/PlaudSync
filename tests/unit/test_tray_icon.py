"""icon.py — PIL Image factory pro 3 stavy ikony."""
from __future__ import annotations

from PIL import Image

from plaudsync.tray.icon import make_icon_image


def test_make_icon_idle_returns_image():
    img = make_icon_image("idle")
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)


def test_make_icon_running_returns_image():
    img = make_icon_image("running")
    assert isinstance(img, Image.Image)


def test_make_icon_error_returns_image():
    img = make_icon_image("error")
    assert isinstance(img, Image.Image)


def test_make_icon_idle_and_error_visually_different():
    """Hash by se měl lišit (různé barvy)."""
    img_idle = make_icon_image("idle")
    img_error = make_icon_image("error")
    assert img_idle.tobytes() != img_error.tobytes()


def test_make_icon_unknown_state_falls_back_to_idle():
    img = make_icon_image("nonsense")
    img_idle = make_icon_image("idle")
    assert img.tobytes() == img_idle.tobytes()
