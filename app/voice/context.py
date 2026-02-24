from __future__ import annotations

from typing import Any

from app.core.state import AppState


def build_board_context(state: AppState, *, max_inventory: int = 6, max_shopping: int = 8, max_memos: int = 2) -> dict[str, Any]:
    reminders = list(getattr(state.model, "reminders", []) or [])
    fridge = [r for r in reminders if str(getattr(r, "category", "") or "") == "fridge"]
    shopping = [r for r in reminders if str(getattr(r, "category", "") or "") != "fridge"]

    def _pack_items(items: list[Any], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in items[: max(0, int(limit))]:
            out.append(
                {
                    "title": str(getattr(r, "title", "") or ""),
                    "right": str(getattr(r, "right", "") or ""),
                    "completed": bool(getattr(r, "completed", False)),
                }
            )
        return out

    memos = list(getattr(state.model, "memos", []) or [])
    memo_items: list[dict[str, Any]] = []
    for m in memos[: max(0, int(max_memos))]:
        memo_items.append(
            {
                "text": str(getattr(m, "text", "") or "")[:120],
                "author": str(getattr(m, "author", "") or ""),
            }
        )

    ui = getattr(state, "ui", None)
    return {
        "screen": str(getattr(getattr(ui, "screen", None), "value", getattr(ui, "screen", "home"))),
        "inventory": {
            "count": len(fridge),
            "items": _pack_items(fridge, max_inventory),
        },
        "shopping": {
            "count": len(shopping),
            "items": _pack_items(shopping, max_shopping),
        },
        "timer": {
            "seconds": int(getattr(ui, "timer_seconds", 0) or 0),
            "running": bool(getattr(ui, "timer_running", False)),
        },
        "memos": memo_items,
    }
