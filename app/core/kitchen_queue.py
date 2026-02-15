from __future__ import annotations

from app.core.state import AppState


def _max_rows(theme: dict | None, key: str, default: int) -> int:
    raw = default if theme is None else theme.get(key, default)
    try:
        return max(1, int(raw))
    except Exception:
        return default


def kitchen_queue_theme_key(theme: dict | None = None) -> str:
    """Cache key for queue-shaping theme knobs."""
    inv_max_rows = _max_rows(theme, "b_inventory_max_rows", 3)
    shop_max_rows = _max_rows(theme, "b_shopping_max_rows", 5)
    return f"{inv_max_rows}:{shop_max_rows}"


def kitchen_visible_task_indices(state: AppState, theme: dict | None = None) -> list[int]:
    """Visible focus/click queue for kitchen home: fridge first, then shopping."""
    # Prefer the exact render-time queue when available.
    cached_rids = [str(rid) for rid in getattr(state.ui, "kitchen_visible_rids", []) if rid]
    cached_theme_key = str(getattr(state.ui, "kitchen_visible_theme_key", "") or "")
    if cached_rids and cached_theme_key == kitchen_queue_theme_key(theme):
        rid_to_idx = {r.rid: i for i, r in enumerate(state.model.reminders)}
        cached_idxs: list[int] = []
        for rid in cached_rids:
            idx = rid_to_idx.get(rid)
            if idx is None:
                continue
            if state.model.reminders[idx].completed:
                continue
            cached_idxs.append(idx)
        # If cache became partial (e.g., focused item just toggled to completed),
        # rebuild from model to avoid a temporary shortened focus queue.
        if cached_idxs and len(cached_idxs) == len(cached_rids):
            return cached_idxs

    inv_max_rows = _max_rows(theme, "b_inventory_max_rows", 3)
    shop_max_rows = _max_rows(theme, "b_shopping_max_rows", 5)

    fridge: list[int] = []
    shop: list[int] = []

    for i, r in enumerate(state.model.reminders):
        if r.completed:
            continue
        if (r.category or "") == "fridge":
            if len(fridge) < inv_max_rows:
                fridge.append(i)
        else:
            if len(shop) < shop_max_rows:
                shop.append(i)

    return fridge + shop
