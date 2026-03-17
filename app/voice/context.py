from __future__ import annotations

from typing import Any

from app.core.family_board import active_memos
from app.core.state import AppState


def build_board_context(
    state: AppState,
    *,
    max_inventory: int = 6,
    max_shopping: int = 8,
    max_memos: int = 2,
    max_recent_action_groups: int = 4,
) -> dict[str, Any]:
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

    memos = active_memos(list(getattr(state.model, "memos", []) or []))
    memo_items: list[dict[str, Any]] = []
    for m in memos[: max(0, int(max_memos))]:
        memo_items.append(
            {
                "text": str(getattr(m, "text", "") or "")[:120],
                "author": str(getattr(m, "author", "") or ""),
            }
        )

    ui = getattr(state, "ui", None)
    recent_groups = list(getattr(ui, "voice_recent_action_groups", []) or [])
    packed_recent_groups: list[dict[str, Any]] = []
    for g in recent_groups[: max(0, int(max_recent_action_groups))]:
        if not isinstance(g, dict):
            continue
        actions = g.get("actions")
        packed_actions: list[dict[str, Any]] = []
        if isinstance(actions, list):
            for a in actions[:4]:
                if not isinstance(a, dict):
                    continue
                tool = str(a.get("tool") or "").strip()
                args = a.get("args") if isinstance(a.get("args"), dict) else {}
                if not tool:
                    continue
                packed_actions.append({"tool": tool, "args": args})
        if not packed_actions:
            continue
        packed_recent_groups.append(
            {
                "at": float(g.get("at") or 0.0),
                "transcript": str(g.get("transcript") or "")[:180],
                "status": str(g.get("status") or ""),
                "message": str(g.get("message") or "")[:180],
                "actions": packed_actions,
            }
        )

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
        "history": {
            "undoable_count": len(list(getattr(ui, "voice_done_action_groups", []) or [])),
            "redoable_count": len(list(getattr(ui, "voice_redo_action_groups", []) or [])),
        },
        "recent_action_groups": packed_recent_groups,
    }
