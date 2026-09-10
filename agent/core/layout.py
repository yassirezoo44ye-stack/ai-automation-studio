"""
Flow Device Agent — Edge Detection and Layout Geometry

Implements the edge-switching algorithm:
  1. Detect if cursor has crossed a screen boundary
  2. Find the target device based on configured layout geometry
  3. Compute relative cursor position in the target device's space
  4. Return the switch data for the controller

Virtual canvas model:
  Each device occupies a rect: (position_x, position_y, width, height)
  These are set by the user in the Device Layout Editor.
  Positions may be arbitrary — not just horizontal strips.

Cross-platform: no OS-specific imports. Pure geometry.
"""
from __future__ import annotations

from typing import Optional


def detect_edge_crossing(
    x: int,
    y: int,
    layout: list[dict],
    current_device_id: str,
    edge_margin: int = 2,
) -> Optional[tuple[str, dict]]:
    """
    Detect if the cursor at (x, y) on the current device has crossed an edge.

    Args:
        x, y: Cursor position in the CURRENT device's coordinate space.
        layout: List of member dicts with position_x, position_y, width, height, device_id.
        current_device_id: Which device the cursor is currently on.
        edge_margin: Pixels from the edge that trigger a crossing check.

    Returns:
        (direction, target_member) or None if no crossing.
    """
    current = _find_member(layout, current_device_id)
    if current is None:
        return None

    cx1 = current["position_x"]
    cy1 = current["position_y"]
    cx2 = cx1 + current["width"]
    cy2 = cy1 + current["height"]

    # Translate local cursor to virtual canvas coordinates
    vx = cx1 + x
    vy = cy1 + y

    # Detect which edge is being crossed
    direction = None
    if x >= current["width"] - edge_margin:
        direction = "right"
    elif x <= edge_margin:
        direction = "left"
    elif y >= current["height"] - edge_margin:
        direction = "bottom"
    elif y <= edge_margin:
        direction = "top"

    if direction is None:
        return None

    # Find the best adjacent device in that direction
    from app.services.device_control import find_target_device
    target = find_target_device(vx, vy, layout, current_device_id, direction)
    if target is None:
        return None

    return direction, target


def compute_switch(
    x: int,
    y: int,
    layout: list[dict],
    from_device_id: str,
    to_member: dict,
) -> Optional[dict]:
    """
    Compute the switch data: translate cursor position from source to target.

    Returns dict with:
      from_device, to_device, target_x, target_y (in target's coordinate space)
    """
    from_member = _find_member(layout, from_device_id)
    if from_member is None:
        return None

    from app.services.device_control import translate_cursor

    target_x, target_y = translate_cursor(
        x_source=float(x),
        y_source=float(y),
        width_source=float(from_member["width"]),
        height_source=float(from_member["height"]),
        width_target=float(to_member["width"]),
        height_target=float(to_member["height"]),
    )

    return {
        "from_device": from_device_id,
        "to_device":   to_member["device_id"],
        "target_x":    target_x,
        "target_y":    target_y,
    }


def _find_member(layout: list[dict], device_id: str) -> Optional[dict]:
    return next((m for m in layout if m.get("device_id") == device_id), None)


# ── Pure unit tests (no OS dependency) ────────────────────────────────────────

def test_translate_cursor_basic() -> None:
    """Translate from 1920x1080 to 2560x1440 at center → center."""
    from app.services.device_control import translate_cursor
    tx, ty = translate_cursor(960, 540, 1920, 1080, 2560, 1440)
    assert tx == 960 * 2560 // 1920, f"Expected {960 * 2560 // 1920} got {tx}"
    assert ty == 540 * 1440 // 1080, f"Expected {540 * 1440 // 1080} got {ty}"


def test_translate_cursor_clamp() -> None:
    """Clamp to valid bounds — never negative or out of range."""
    from app.services.device_control import translate_cursor
    tx, ty = translate_cursor(9999, 9999, 1920, 1080, 1920, 1080)
    assert tx == 1919, f"Expected 1919 got {tx}"
    assert ty == 1079, f"Expected 1079 got {ty}"


def test_translate_cursor_zero_size() -> None:
    from app.services.device_control import translate_cursor
    tx, ty = translate_cursor(100, 100, 0, 0, 1920, 1080)
    assert tx == 0 and ty == 0


def test_edge_crossing_right() -> None:
    layout = [
        {"device_id": "A", "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        {"device_id": "B", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
    ]
    result = detect_edge_crossing(1919, 540, layout, "A", edge_margin=5)
    assert result is not None, "Should detect right edge crossing"
    direction, target = result
    assert direction == "right"
    assert target["device_id"] == "B"


def test_edge_no_crossing_center() -> None:
    layout = [
        {"device_id": "A", "position_x": 0, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        {"device_id": "B", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
    ]
    result = detect_edge_crossing(960, 540, layout, "A")
    assert result is None, "Center cursor should not trigger a switch"
