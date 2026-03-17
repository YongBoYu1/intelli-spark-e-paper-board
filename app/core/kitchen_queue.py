from __future__ import annotations

from app.core.state import AppState

KITCHEN_FOCUS_CLOCK = "clock"
KITCHEN_FOCUS_WEATHER = "weather"
KITCHEN_FOCUS_INVENTORY_HEADER = "inventory_header"
KITCHEN_FOCUS_INVENTORY_ITEM = "inventory_item"
KITCHEN_FOCUS_REMINDERS_HEADER = "reminders_header"
KITCHEN_FOCUS_REMINDERS_ITEM = "reminders_item"
KITCHEN_FOCUS_NONE = "none"


def _normalized_right_angle(raw) -> int:
    try:
        deg = int(raw or 0)
    except Exception:
        deg = 0
    return (((deg % 360) + 45) // 90 * 90) % 360


def _resolved_home_variant(state: AppState | None, theme: dict | None = None) -> str:
    variant = str((theme or {}).get("home_variant") or "kitchen").strip().lower()
    rotation_deg = 0 if state is None else getattr(state.ui, "rotation_deg", 0)
    rot = _normalized_right_angle(rotation_deg)
    if variant == "kitchen_portrait" and rot in (0, 180):
        return "kitchen"
    return variant


def _inventory_default_rows(state: AppState | None, theme: dict | None = None) -> int:
    return 4 if _resolved_home_variant(state, theme) == "kitchen_portrait" else 3


def _max_rows(theme: dict | None, key: str, default: int) -> int:
    raw = default if theme is None else theme.get(key, default)
    try:
        return max(1, int(raw))
    except Exception:
        return default


def kitchen_queue_theme_key(state: AppState | None = None, theme: dict | None = None) -> str:
    """Cache key for queue-shaping theme knobs."""
    inv_max_rows = _max_rows(theme, "b_inventory_max_rows", _inventory_default_rows(state, theme))
    shop_max_rows = _max_rows(theme, "b_shopping_max_rows", 5)
    return f"{inv_max_rows}:{shop_max_rows}"


def _home_hidden_rids(state: AppState) -> set[str]:
    return {
        str(rid)
        for rid in getattr(state.ui, "home_hidden_rids", [])
        if str(rid or "").strip()
    }


def kitchen_visible_task_indices(state: AppState, theme: dict | None = None) -> list[int]:
    """Visible focus/click queue for kitchen home: fridge first, then shopping."""
    # Prefer the exact render-time queue when available.
    cached_rids = [str(rid) for rid in getattr(state.ui, "kitchen_visible_rids", []) if rid]
    cached_theme_key = str(getattr(state.ui, "kitchen_visible_theme_key", "") or "")
    cached_reminders_version = int(getattr(state.ui, "kitchen_visible_reminders_version", -1))
    current_reminders_version = int(getattr(state.ui, "reminders_version", 0))
    if (
        cached_rids
        and cached_theme_key == kitchen_queue_theme_key(state, theme)
        and cached_reminders_version == current_reminders_version
    ):
        rid_to_indices: dict[str, list[int]] = {}
        for i, reminder in enumerate(state.model.reminders):
            rid = str(getattr(reminder, "rid", "") or "")
            rid_to_indices.setdefault(rid, []).append(i)
        cached_idxs: list[int] = []
        for rid in cached_rids:
            idxs = rid_to_indices.get(rid) or []
            if not idxs:
                continue
            cached_idxs.append(idxs.pop(0))
        if cached_idxs and len(cached_idxs) == len(cached_rids):
            return cached_idxs

    inv_max_rows = _max_rows(theme, "b_inventory_max_rows", _inventory_default_rows(state, theme))
    shop_max_rows = _max_rows(theme, "b_shopping_max_rows", 5)
    hidden_rids = _home_hidden_rids(state)

    fridge: list[int] = []
    shop: list[int] = []

    for i, r in enumerate(state.model.reminders):
        rid = str(getattr(r, "rid", "") or "").strip()
        if rid and rid in hidden_rids:
            continue
        if (r.category or "") == "fridge":
            target = fridge
        else:
            target = shop
        if target is fridge and len(fridge) >= inv_max_rows:
            continue
        if target is shop and len(shop) >= shop_max_rows:
            continue
        target.append(i)

    return fridge + shop


def kitchen_visible_section_indices(state: AppState, theme: dict | None = None) -> tuple[list[int], list[int]]:
    all_visible = kitchen_visible_task_indices(state, theme)
    fridge: list[int] = []
    reminders: list[int] = []
    for idx in all_visible:
        r = state.model.reminders[idx]
        if (r.category or "") == "fridge":
            fridge.append(idx)
        else:
            reminders.append(idx)
    return fridge, reminders


def kitchen_focus_count(state: AppState, theme: dict | None = None) -> int:
    fridge, reminders = kitchen_visible_section_indices(state, theme)
    # [CLOCK, WEATHER, INVENTORY_ITEMS..., REMINDERS_ITEMS...]
    return 2 + len(fridge) + len(reminders)


def kitchen_focus_target(
    state: AppState,
    focused_index: int,
    theme: dict | None = None,
) -> tuple[str, int | None]:
    idx = int(focused_index or 0)
    if idx <= 0:
        return (KITCHEN_FOCUS_CLOCK, None)
    if idx == 1:
        return (KITCHEN_FOCUS_WEATHER, None)

    fridge, reminders = kitchen_visible_section_indices(state, theme)
    pos = idx - 2

    if pos < len(fridge):
        return (KITCHEN_FOCUS_INVENTORY_ITEM, fridge[pos])
    pos -= len(fridge)

    if pos < len(reminders):
        return (KITCHEN_FOCUS_REMINDERS_ITEM, reminders[pos])

    return (KITCHEN_FOCUS_NONE, None)
