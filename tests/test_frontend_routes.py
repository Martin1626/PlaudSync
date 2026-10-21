"""Every header tab must have a route in the router main.tsx actually mounts.

The frontend has no JS test runner; a tab without a route renders React Router's
"404 Not Found" error screen in the tray UI.
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"


def test_every_header_tab_has_a_route_in_main_router() -> None:
    header = (FRONTEND / "components" / "Header.tsx").read_text(encoding="utf-8")
    main = (FRONTEND / "main.tsx").read_text(encoding="utf-8")

    tabs = set(re.findall(r'<NavTab\s+to="([^"]+)"', header))
    routes = set(re.findall(r'path:\s*"([^"]+)"', main))

    assert tabs, "no NavTab found in Header.tsx"
    assert tabs <= routes, f"tabs without a route: {sorted(tabs - routes)}"
